import asyncio
import os
import json
import shutil
import tempfile
import logging
from dataclasses import dataclass
from enum import Enum
from .interface import SandboxInterface, SandboxCreationError, SandboxOperationError, SandboxStreamClosed, SandboxError
from .types import SandboxOutputEvent, OutputType, CodeLanguage, SandboxStateEvent
from .execution import Execution

logger = logging.getLogger(__name__)

class GVisorState(str, Enum):
    """Represents the lifecycle state of the gVisor sandbox container."""
    INITIALIZED = "INITIALIZED"
    RUNNING = "RUNNING"
    CHECKPOINTED = "CHECKPOINTED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"

@dataclass
class GVisorConfig:
    """Configuration for the GVisorSandbox."""
    # Whether to use sudo for runsc commands.
    use_sudo: bool = False
    # Whether to run in rootless mode.
    rootless: bool = False
    # The base directory for sandbox root directories.
    root_dir_base: str = "/tmp"
    # The base directory for OCI bundles.
    bundle_dir_base: str = "/tmp"
    # Whether to ignore cgroup errors.
    ignore_cgroups: bool = False
    # The gVisor platform to use (e.g., systrap, ptrace, kvm).
    platform: str = "systrap"
    # The network mode to use (e.g., host, none).
    network: str = "host"
    # Whether to enable a writable filesystem.
    writable_filesystem: bool = True
    # Whether to enable gVisor's debug logging.
    debug: bool = False
    # Whether to enable strace for sandboxed processes.
    strace: bool = False
    # The base directory for gVisor's debug logs.
    # The actual log path directory will be this plus the sandbox ID.
    # runsc will create different log files in this directory.
    debug_log_dir: str = "/tmp/runsc"

class GVisorSandbox(SandboxInterface):
    """
    A sandbox implementation that uses gVisor ('runsc') to execute code.
    """
    def __init__(self, sandbox_id: str, config: GVisorConfig):
        self._sandbox_id = sandbox_id
        self._config = config
        self._bundle_dir = os.path.join(config.bundle_dir_base, f"runsc_bundle_{sandbox_id}")
        # Each sandbox gets a unique, named root directory.
        self._root_dir = os.path.join(config.root_dir_base, f"runsc_root_{sandbox_id}")
        self._current_execution = None
        self._drain_tasks = []
        self._is_attached = False
        self._state = GVisorState.INITIALIZED
        logger.info(f"GVISOR: Initialized for sandbox_id: {self.sandbox_id}")

    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    @property
    def is_attached(self) -> bool:
        return self._is_attached

    @is_attached.setter
    def is_attached(self, value: bool):
        self._is_attached = value

    def _build_runsc_cmd(self, *args):
        """Builds a runsc command, adding configured flags."""
        cmd = ["runsc"]
        if self._config.use_sudo:
            cmd.insert(0, "sudo")
        
        # Add debugging flags if enabled
        if self._config.debug:
            log_path = os.path.join(self._config.debug_log_dir, self.sandbox_id) + "/"
            os.makedirs(log_path, exist_ok=True)
            cmd.extend(["--debug-log", log_path])
            cmd.append("--debug")
        if self._config.strace:
            cmd.append("--strace")

        # Always use the unique root directory.
        cmd.extend([f"--root={self._root_dir}"])
        if self._config.rootless:
            cmd.append("--rootless")
        if self._config.ignore_cgroups:
            cmd.append("--ignore-cgroups")
        if self._config.platform:
            cmd.extend(["--platform", self._config.platform])
        
        # Flags that only apply to the 'run' command.
        if "run" in args:
            cmd.extend(["--network", self._config.network])
            if self._config.writable_filesystem:
                cmd.append("--overlay2=root:memory")

        cmd.extend(args)
        return cmd

    async def _run_sync_command(self, cmd, check=True, wait_for_output=True):
        """
        Helper to run a synchronous command.

        Args:
            cmd: The command to execute as a list of strings.
            check: If True, raises SandboxOperationError if the command returns a non-zero exit code.
            wait_for_output: If True, waits for the process to terminate and reads stdout/stderr.
                             If False, only waits for the process to exit (for detached processes)
                             and does not read from the output pipes to avoid deadlocks.
        """
        logger.info(f"GVISOR: Running command: {' '.join(cmd)})")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        if not wait_for_output:
            # For detached commands, we must still drain stdout/stderr to prevent
            # the child process from blocking if the pipe buffer fills up.
            # We do this concurrently while waiting for the process to exit.
            async def drain_pipe(stream, name):
                while not stream.at_eof():
                    data = await stream.read(1024) # Read and discard
                    logger.debug(f"GVISOR: DRAIN ({name}): {data}")

            drain_stdout = asyncio.create_task(drain_pipe(proc.stdout, "stdout"))
            drain_stderr = asyncio.create_task(drain_pipe(proc.stderr, "stderr"))
            self._drain_tasks.extend([drain_stdout, drain_stderr])

            try:
                # `runsc run --detach` should exit quickly.
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise SandboxOperationError(f"Command {' '.join(cmd)} timed out.")

            if check and proc.returncode != 0:
                # We can't reliably get stderr here because we were just draining,
                # but we can report the exit code.
                raise SandboxOperationError(f"Command failed: {' '.join(cmd)} with exit code {proc.returncode}")
            return "", ""

        # For regular commands, wait for output.
        stdout, stderr = await proc.communicate()
        if check and proc.returncode != 0:
            cmd_str = " ".join(cmd)
            raise SandboxOperationError(f"Command failed: {cmd_str}\n{stderr.decode()}")
        logger.info(f"GVISOR: Command finished: {' '.join(cmd)})")
        return stdout.decode(), stderr.decode()

    def _prepare_bundle(self):
        """
        Creates the OCI bundle directory and config.json.
        """
        os.makedirs(self._bundle_dir, exist_ok=True)
        mounts = [
            {"destination": "/proc", "type": "proc", "source": "proc"},
            {
                "destination": self._bundle_dir, "type": "bind",
                "source": self._bundle_dir, "options": ["rbind", "rw"]
            }
        ]
        root_config = {"path": "/", "readonly": not self._config.writable_filesystem}
        config = {
            "ociVersion": "1.0.0",
            "process": {
                "user": {"uid": 0, "gid": 0},
                "args": ["sh", "-c", "while true; do sleep 3600; done"],
                "cwd": "/",
                "env": [
                    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                    "PYTHONUNBUFFERED=1"
                ]
            },
            "root": root_config,
            "mounts": mounts
        }
        config_path = os.path.join(self._bundle_dir, "config.json")
        logger.info(f"--- Writing config.json to {config_path} ---")
        logger.info(json.dumps(config, indent=4))
        with open(config_path, "w") as f:
            json.dump(config, f)

    async def create(self):
        """
        Creates the OCI bundle and starts a long-running, detached container.
        """
        logger.info(f"GVISOR: Creating container for sandbox_id: {self.sandbox_id}")
        try:
            self._prepare_bundle()
            # Start the container in detached mode.
            run_cmd = self._build_runsc_cmd("run", "--detach", "--bundle", self._bundle_dir, self.sandbox_id)
            await self._run_sync_command(run_cmd, wait_for_output=False)
            self._state = GVisorState.RUNNING
            logger.info(f"GVISOR: Container created for sandbox_id: {self.sandbox_id}")

        except Exception as e:
            logger.info(f"GVISOR: Failed to create container for sandbox_id: {self.sandbox_id}: {e}")
            self._state = GVisorState.FAILED
            await self.delete()
            raise SandboxCreationError(f"Failed to create gVisor container: {e}")

    async def execute(self, language: CodeLanguage, code: str):
        """
        Executes the given code in the sandbox using 'runsc exec'.
        """
        logger.info(f"GVISOR: Executing code in sandbox_id: {self.sandbox_id}")
        # TODO: Refactor to support concurrent executions.
        if self._current_execution and self._current_execution.is_running:
            raise SandboxOperationError("An execution is already in progress.")

        # The previous execution is finished, so we can proceed.
        self._current_execution = None

        if language == CodeLanguage.PYTHON:
            code_filename = "main.py"
            exec_args = ["python3", "-u", os.path.join(self._bundle_dir, code_filename)]
        elif language == CodeLanguage.BASH:
            code_filename = "main.sh"
            exec_args = ["bash", os.path.join(self._bundle_dir, code_filename)]
        else:
            raise SandboxError(f"Unsupported language: {language}")

        # Write the code to a file inside the bundle directory, which is mounted
        # into the container.
        code_path_host = os.path.join(self._bundle_dir, code_filename)
        with open(code_path_host, "w") as f:
            f.write(code)

        # Execute the code.
        exec_cmd = self._build_runsc_cmd(
            "exec", "--cwd", "/", self.sandbox_id, *exec_args
        )
        
        logger.info(f"GVISOR: Starting execution process for sandbox_id: {self.sandbox_id}")
        process = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        self._current_execution = Execution(process)
        await self._current_execution.start_streaming()
        logger.info(f"GVISOR: Execution started for sandbox_id: {self.sandbox_id}")

    async def connect(self):
        """
        Connects a client to the sandbox's output stream.
        """
        if not self._current_execution:
            raise SandboxError("No process is running in the sandbox.")
        
        yield {"type": "status_update", "status": SandboxStateEvent.SANDBOX_EXECUTION_RUNNING.value}
        
        async for event in self._current_execution.connect():
            yield event
        
        if self._current_execution:
            await self._current_execution.wait()
            
        yield {"type": "status_update", "status": SandboxStateEvent.SANDBOX_EXECUTION_DONE.value}

    async def write_to_stdin(self, data: str):
        """Writes data to the stdin of the running process."""
        if not self._current_execution:
            raise SandboxOperationError("No process is running in the sandbox.")
        await self._current_execution.write_to_stdin(data)

    async def stop(self):
        """Stops the container and any running exec process."""
        logger.info(f"GVISOR ({self.sandbox_id}): Stopping...")
        if self._current_execution:
            execution_to_stop = self._current_execution
            self._current_execution = None
            await execution_to_stop.stop()

        kill_cmd = self._build_runsc_cmd("kill", self.sandbox_id, "SIGKILL")
        await self._run_sync_command(kill_cmd, check=False)
        self._state = GVisorState.STOPPED
        logger.info(f"GVISOR ({self.sandbox_id}): Stopped.")

    async def delete(self):
        """Deletes the container and its bundle."""
        logger.info(f"GVISOR ({self.sandbox_id}): Deleting...")
        await self.stop()

        logger.debug(f"GVISOR ({self.sandbox_id}): Canceling drain tasks...")
        for task in self._drain_tasks:
            task.cancel()
        self._drain_tasks.clear()
        logger.debug(f"GVISOR ({self.sandbox_id}): Drain tasks canceled.")

        delete_cmd = self._build_runsc_cmd("delete", "--force", self.sandbox_id)
        # Don't wait for output to avoid blocking for too long.
        await self._run_sync_command(delete_cmd, check=False)

        if os.path.exists(self._bundle_dir):
            shutil.rmtree(self._bundle_dir)
        if os.path.exists(self._root_dir):
            shutil.rmtree(self._root_dir)

        logger.info(f"GVISOR ({self.sandbox_id}): Deleted.")

    async def checkpoint(self, checkpoint_path: str) -> None:
        """
        Creates a checkpoint of the sandbox's state using 'runsc checkpoint'.
        """
        logger.info(f"GVISOR ({self.sandbox_id}): Checkpointing to {checkpoint_path}")
        if self._current_execution and self._current_execution.is_running:
            raise SandboxOperationError("Cannot checkpoint while an execution is in progress.")

        cmd = self._build_runsc_cmd("checkpoint", f"--image-path={checkpoint_path}", self.sandbox_id)
        await self._run_sync_command(cmd)
        self._state = GVisorState.CHECKPOINTED
        logger.info(f"GVISOR ({self.sandbox_id}): Checkpointed successfully.")

    async def restore(self, checkpoint_path: str) -> None:
        """
        Restores the sandbox's state from a checkpoint using 'runsc restore'.
        """
        logger.info(f"GVISOR ({self.sandbox_id}): Restoring from {checkpoint_path}")
        try:
            self._prepare_bundle()
            cmd = self._build_runsc_cmd(
                "restore",
                f"--image-path={checkpoint_path}",
                "--bundle", self._bundle_dir,
                self.sandbox_id
            )
            await self._run_sync_command(cmd, wait_for_output=False)
            self._state = GVisorState.RUNNING
            logger.info(f"GVISOR ({self.sandbox_id}): Restored successfully.")
        except Exception as e:
            logger.info(f"GVISOR ({self.sandbox_id}): Failed to restore: {e}")
            self._state = GVisorState.FAILED
            await self.delete()
            raise SandboxCreationError(f"Failed to restore gVisor container: {e}")
