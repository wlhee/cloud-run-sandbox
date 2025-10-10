import asyncio
import os
import json
import shutil
import tempfile
import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from .interface import (
    SandboxInterface, SandboxState, SandboxCreationError, SandboxOperationError,
    SandboxExecutionError, SandboxStreamClosed, SandboxCheckpointError, SandboxRestoreError,
    SandboxExecutionInProgressError, SandboxError, SandboxSnapshotFilesystemError
)
from .types import SandboxOutputEvent, OutputType, CodeLanguage, SandboxStateEvent
from .process import Process

logger = logging.getLogger(__name__)

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
    network: str = "sandbox"
    # Whether to enable a writable filesystem.
    writable_filesystem: bool = True
    # The IP address to assign to the sandbox.
    ip_address: Optional[str] = None
    # Whether to enable gVisor's debug logging.
    debug: bool = False
    # Whether to enable strace for sandboxed processes.
    strace: bool = False
    # Whether to enable packet logging in debug logs.
    log_packets: bool = False
    # The base directory for gVisor's debug logs.
    # The actual log path directory will be this plus the sandbox ID.
    # runsc will create different log files in this directory.
    debug_log_dir: str = "/tmp/runsc"
    # The path to the filesystem snapshot to create the sandbox from.
    filesystem_snapshot_path: Optional[str] = None

class GVisorSandbox(SandboxInterface):
    """
    A sandbox implementation that uses gVisor ('runsc') to execute code.

    This class enforces a strict lifecycle state machine:

    INITIALIZED: The initial state after the object is created.
        - `create()` -> RUNNING
        - `restore()` -> RUNNING
        - `delete()` -> STOPPED (no-op, cleans up dirs)

    RUNNING: The sandbox container is running and ready to execute code.
        - `execute()` -> RUNNING (spawns an exec process)
        - `checkpoint()` -> CHECKPOINTED
        - `delete()` -> STOPPED (deletes the container and dirs)

    CHECKPOINTED: The sandbox state has been saved to disk, but the container
                  is still running and can be used.
        - `delete()` -> STOPPED

    STOPPED: The container has been stopped and resources have been released.
             This is a terminal state for the container instance. To continue,
             a new sandbox must be created (e.g., by restoring).
        - `delete()` -> STOPPED (no-op, cleans up dirs)

    FAILED: A critical error occurred. This is a terminal state.
    """
    def __init__(self, sandbox_id: str, config: GVisorConfig):
        self._sandbox_id = sandbox_id
        self._container_id = self._generate_container_id()
        self._config = config
        self._bundle_dir = os.path.join(config.bundle_dir_base, f"runsc_bundle_{sandbox_id}")
        # Each sandbox gets a unique, named root directory.
        self._root_dir = os.path.join(config.root_dir_base, f"runsc_root_{sandbox_id}")
        self._main_process: Process = None
        self._exec_process: Process = None
        self._drain_tasks = []
        self._is_attached = False
        self._state = SandboxState.INITIALIZED
        self._network_cleanup_cmds = []
        logger.info(f"GVISOR: Initialized for sandbox_id: {self.sandbox_id}")

    def _generate_container_id(self) -> str:
        """Generates a unique container ID."""
        return f"runsc-cont-{self.sandbox_id}-{uuid.uuid4().hex[:8]}"

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
            if self._config.log_packets:
                cmd.append("--log-packets")
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
        
        # Flags that only apply to commands that start or modify the container.
        if "run" in args or "restore" in args:
            cmd.extend(["--network", self._config.network])
            if self._config.writable_filesystem:
                cmd.append("--overlay2=root:memory")
        
        # Supporting `ping`
        if "exec" in args:
            cmd.append("--net-raw")

        cmd.extend(args)
        return cmd

    async def _run_sync_command(self, cmd, check=True, sudo=False):
        """
        Helper to run a synchronous command that is expected to terminate.
        """
        if sudo:
            cmd.insert(0, "sudo")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError:
            raise SandboxOperationError(f"Command '{cmd[0]}' not found.")

        if check and proc.returncode != 0:
            cmd_str = " ".join(cmd)
            raise SandboxOperationError(f"Command failed: {cmd_str}\n{stderr.decode()}")
        return stdout.decode(), stderr.decode()

    async def _setup_network(self):
        """
        Sets up a dedicated network namespace for the sandbox, including a veth pair
        and iptables rules for internet access.
        """
                    
        if not self._config.ip_address:
            return
        
        logger.info(f"GVISOR: Setting up network for sandbox_id {self.sandbox_id}, ip_address: {self._config.ip_address}")

        # Use a short unique ID for network device names to stay within length limits.
        unique_id = self._sandbox_id.split('-')[-1]
        veth = f"veth-{unique_id}"
        peer = f"peer-{unique_id}"
        namespace = self._sandbox_id
        
        # Calculate the gateway IP (peer IP) from the sandbox IP.
        ip_parts = self._config.ip_address.split('.')
        peer_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.{int(ip_parts[3]) + 1}"

        # Get the host's default network interface and MTU.
        stdout, _ = await self._run_sync_command(["ip", "route", "show", "default"], sudo=True)
        host_if = stdout.split(' ')[4]
        stdout, _ = await self._run_sync_command(["ip", "link", "show", host_if], sudo=True)
        mtu = stdout.split('mtu ')[1].split(' ')[0]

        setup_cmds = [
            f"ip link add {veth} mtu {mtu} type veth peer name {peer}",
            f"ip addr add {peer_ip}/24 dev {peer}",
            f"ip link set {peer} up",
            f"ip netns add {namespace}",
            f"ip link set {veth} netns {namespace}",
            f"ip netns exec {namespace} ip addr add {self._config.ip_address}/24 dev {veth}",
            f"ip netns exec {namespace} ip link set {veth} up",
            f"ip netns exec {namespace} ip link set lo up",
            f"ip netns exec {namespace} ip route add default via {peer_ip}",
            "sysctl -w net.ipv4.ip_forward=1",
            f"iptables -t nat -A POSTROUTING -s {self._config.ip_address} -o {host_if} -j MASQUERADE",
            f"iptables -A FORWARD -i {host_if} -o {peer} -j ACCEPT",
            f"iptables -A FORWARD -o {host_if} -i {peer} -j ACCEPT",
        ]

        # Define cleanup commands in reverse order.
        self._network_cleanup_cmds = [
            f"ip link del {peer}",
            f"ip netns del {namespace}",
            f"iptables -t nat -D POSTROUTING -s {self._config.ip_address} -o {host_if} -j MASQUERADE",
            f"iptables -D FORWARD -i {host_if} -o {peer} -j ACCEPT",
            f"iptables -D FORWARD -o {host_if} -i {peer} -j ACCEPT",
        ]

        for cmd_str in setup_cmds:
            stdout, stderr = await self._run_sync_command(cmd_str.split(), sudo=True)
            if stderr:
                logger.warning(f"GVISOR ({self.sandbox_id}) setup stderr: {stderr}")
        logger.info(f"GVISOR: Finished setting up network for sandbox_id: {self.sandbox_id}")

    async def _teardown_network(self):
        """
        Tears down the network namespace and related resources."""
        if not self._network_cleanup_cmds:
            return
        
        logger.info(f"GVISOR ({self.sandbox_id}): Tearing down network...")
        for cmd_str in self._network_cleanup_cmds:
            try:
                stdout, stderr = await self._run_sync_command(cmd_str.split(), sudo=True, check=False)
                if stderr:
                    logger.warning(f"GVISOR ({self.sandbox_id}) teardown stderr: {stderr}")
            except Exception as e:
                logger.warning(f"GVISOR ({self.sandbox_id}): Failed to run network cleanup command '{cmd_str}': {e}")
        self._network_cleanup_cmds = []

    async def _health_check(self) -> bool:
        """
        Checks if the container is in the 'running' state using 'runsc state'.
        Retries a few times to give the container time to start.
        """
        for attempt in range(5):
            try:
                cmd = self._build_runsc_cmd("state", self._container_id)
                stdout, _ = await self._run_sync_command(cmd)
                state = json.loads(stdout)
                if state.get("status") == "running":
                    logger.info(f"GVISOR ({self.sandbox_id}): Health check passed.")
                    return True
            except (SandboxOperationError, json.JSONDecodeError) as e:
                logger.warning(f"GVISOR ({self.sandbox_id}): Health check attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(0.1)
        return False

    async def _start_main_process(self, cmd: list[str], operation_name: str) -> Process:
        """
        Starts the main container process and performs a health check.
        
        Args:
            cmd: The runsc command to execute.
            operation_name: The name of the operation ('create' or 'restore') for logging.
        
        Returns:
            The started Process instance.
            
        Raises:
            SandboxCreationError: If the process fails to start or the health check fails.
        """
        print(f"Starting main process with command: {' '.join(cmd)}")
        process = Process(cmd)
        await process.start()

        if not await self._health_check():
            # Best-effort attempt to get stderr from the crashed process
            stderr_output = []
            try:
                async for event in process.stream_outputs():
                    if event["type"] == OutputType.STDERR:
                        stderr_output.append(event["data"])
            except Exception:
                pass # Ignore errors during this best-effort read
            
            await process.stop()
            raise SandboxCreationError(
                f"gVisor container failed to {operation_name}. "
                f"Stderr: {''.join(stderr_output)}"
            )
        
        return process

    def _prepare_bundle(self):
        """
        Creates the OCI bundle directory and config.json.
        """
        os.makedirs(self._bundle_dir, exist_ok=True)
        
        # --- Create network config files ---
        resolv_conf_path = os.path.join(self._bundle_dir, "resolv.conf")
        with open(resolv_conf_path, "w") as f:
            f.write("nameserver 8.8.8.8\n")

        hostname_path = os.path.join(self._bundle_dir, "hostname")
        with open(hostname_path, "w") as f:
            f.write(f"{self._sandbox_id}\n")

        hosts_path = os.path.join(self._bundle_dir, "hosts")
        hosts_content = f"127.0.0.1\tlocalhost\n{self._config.ip_address or '127.0.0.1'}\t{self._sandbox_id}\n"
        with open(hosts_path, "w") as f:
            f.write(hosts_content)

        mounts = [
            {"destination": "/proc", "type": "proc", "source": "proc"},
            {
                "destination": self._bundle_dir, "type": "bind",
                "source": self._bundle_dir, "options": ["rbind", "rw"]
            },
            {
                "destination": "/etc/resolv.conf", "type": "bind",
                "source": resolv_conf_path, "options": ["rbind", "ro"]
            },
            {
                "destination": "/etc/hostname", "type": "bind",
                "source": hostname_path, "options": ["rbind", "ro"]
            },
            {
                "destination": "/etc/hosts", "type": "bind",
                "source": hosts_path, "options": ["rbind", "ro"]
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
            "mounts": mounts,
            "linux": {
                "namespaces": [
                    {"type": "pid"},
                    {"type": "ipc"},
                    {"type": "uts"},
                    {"type": "mount"}
                ]
            }
        }

        # Add network namespace if IP is configured
        if self._config.ip_address:
            config["linux"]["namespaces"].append({
                "type": "network",
                "path": f"/var/run/netns/{self._sandbox_id}"
            })

        if self._config.filesystem_snapshot_path:
            if not os.path.exists(self._config.filesystem_snapshot_path):
                raise SandboxCreationError(f"Filesystem snapshot not found at {self._config.filesystem_snapshot_path}")
            config["annotations"] = {
                "dev.gvisor.tar.rootfs.upper": self._config.filesystem_snapshot_path
            }

        config_path = os.path.join(self._bundle_dir, "config.json")
        logger.info(f"--- Writing config.json to {config_path} ---")
        logger.info(json.dumps(config, indent=4))
        with open(config_path, "w") as f:
            json.dump(config, f)

    async def create(self):
        """
        Creates the OCI bundle and starts a long-running container.
        """
        if self._state != SandboxState.INITIALIZED:
            raise SandboxOperationError(f"Cannot create a sandbox that is not in the INITIALIZED state (current state: {self._state})")
        
        logger.info(f"GVISOR: Creating container '{self._container_id}' for sandbox_id: {self.sandbox_id}")
        try:
            if self._config.network == "sandbox":
                await self._setup_network()

            self._prepare_bundle()
            
            run_cmd_list = ["run", "--bundle", self._bundle_dir, self._container_id]
            run_cmd = self._build_runsc_cmd(*run_cmd_list)

            self._main_process = await self._start_main_process(run_cmd, "create")
            self._state = SandboxState.RUNNING
            logger.info(f"GVISOR: Container created for sandbox_id: {self.sandbox_id}")

        except Exception as e:
            logger.info(f"GVISOR: Failed to create container for sandbox_id: {self.sandbox_id}: {e}")
            self._state = SandboxState.FAILED
            await self.delete()
            raise SandboxCreationError(f"Failed to create gVisor container: {e}")

    async def execute(self, language: CodeLanguage, code: str):
        """
        Executes the given code in the sandbox using 'runsc exec'.
        """
        if self._state != SandboxState.RUNNING:
            raise SandboxOperationError(f"Cannot execute code in a sandbox that is not in the RUNNING state (current state: {self._state})")

        logger.info(f"GVISOR: Executing code in sandbox_id: {self.sandbox_id}")
        if self._exec_process and self._exec_process.is_running:
            raise SandboxOperationError("An execution is already in progress.")

        self._exec_process = None

        if language == CodeLanguage.PYTHON:
            code_filename = "main.py"
            exec_args = ["python3", "-u", os.path.join(self._bundle_dir, code_filename)]
        elif language == CodeLanguage.BASH:
            code_filename = "main.sh"
            exec_args = ["bash", os.path.join(self._bundle_dir, code_filename)]
        else:
            raise SandboxError(f"Unsupported language: {language}")

        code_path_host = os.path.join(self._bundle_dir, code_filename)
        with open(code_path_host, "w") as f:
            f.write(code)

        exec_cmd_list = ["exec", "--cap", "CAP_NET_RAW", "--cwd", "/", self._container_id]
        exec_cmd_list.extend(exec_args)
        exec_cmd = self._build_runsc_cmd(*exec_cmd_list)
        
        logger.info(f"GVISOR: Starting execution process for sandbox_id: {self.sandbox_id}")
        self._exec_process = Process(exec_cmd)
        await self._exec_process.start()

    async def stream_outputs(self):
        """
        Connects a client to the sandbox's output stream.
        """
        exec_process = self._exec_process
        if not exec_process:
            raise SandboxError("No process is running in the sandbox.")
        
        yield {"type": "status_update", "status": SandboxStateEvent.SANDBOX_EXECUTION_RUNNING.value}
        
        try:
            async for event in exec_process.stream_outputs():
                yield event
        except SandboxStreamClosed:
            logger.info(f"GVISOR ({self.sandbox_id}): Exec process stream closed.")
        
        await exec_process.wait()
        yield {"type": "status_update", "status": SandboxStateEvent.SANDBOX_EXECUTION_DONE.value}

    async def write_stdin(self, data: str):
        """Writes data to the stdin of the running process."""
        if not self._exec_process:
            raise SandboxOperationError("No process is running in the sandbox.")
        await self._exec_process.write_stdin(data)

    async def _stop(self):
        """
        Stops the container and any running exec process. This is a no-op if
        the sandbox is already stopped.
        """
        if self._state in [SandboxState.STOPPED, SandboxState.INITIALIZED, SandboxState.FAILED]:
            logger.info(f"GVISOR ({self.sandbox_id}): Stop called on an already stopped or uninitialized sandbox. No-op.")
            return

        logger.info(f"GVISOR ({self.sandbox_id}): Stopping...")
        if self._exec_process and self._exec_process.is_running:
            await self._exec_process.stop()
        self._exec_process = None

        if self._main_process and self._main_process.is_running:
            await self._main_process.stop()
        self._main_process = None

        kill_cmd = self._build_runsc_cmd("kill", self._container_id, "SIGKILL")
        await self._run_sync_command(kill_cmd, check=False)
        self._state = SandboxState.STOPPED
        logger.info(f"GVISOR ({self.sandbox_id}): Stopped.")

    async def delete(self):
        """
        Deletes the container and its bundle. This is a no-op if the sandbox
        is already stopped.
        """
        logger.info(f"GVISOR ({self.sandbox_id}): Deleting...")
        await self._stop()

        logger.debug(f"GVISOR ({self.sandbox_id}): Canceling drain tasks...")
        for task in self._drain_tasks:
            task.cancel()
        self._drain_tasks.clear()
        logger.debug(f"GVISOR ({self.sandbox_id}): Drain tasks canceled.")

        delete_cmd = self._build_runsc_cmd("delete", "--force", self._container_id)
        await self._run_sync_command(delete_cmd, check=False)

        if os.path.exists(self._bundle_dir):
            shutil.rmtree(self._bundle_dir)
        if os.path.exists(self._root_dir):
            shutil.rmtree(self._root_dir)

        await self._teardown_network()
        logger.info(f"GVISOR ({self.sandbox_id}): Deleted.")

    async def checkpoint(self, checkpoint_path: str) -> None:
        """
        Creates a checkpoint of the sandbox's state using 'runsc checkpoint'.
        """
        if self._state != SandboxState.RUNNING:
            raise SandboxOperationError(f"Cannot checkpoint a sandbox that is not in the RUNNING state (current state: {self._state})")

        logger.info(f"GVISOR ({self.sandbox_id}): Checkpointing to {checkpoint_path}")
        if self._exec_process and self._exec_process.is_running:
            raise SandboxExecutionInProgressError("Cannot checkpoint while an execution is in progress.")

        cmd = self._build_runsc_cmd("checkpoint", f"--image-path={checkpoint_path}", self._container_id)
        await self._run_sync_command(cmd)
        self._state = SandboxState.CHECKPOINTED
        logger.info(f"GVISOR ({self.sandbox_id}): Checkpointed successfully.")

    async def restore(self, checkpoint_path: str) -> None:
        """
        Restores the sandbox's state from a checkpoint using 'runsc restore'.
        """
        if self._state != SandboxState.INITIALIZED:
            raise SandboxOperationError(f"Cannot restore a sandbox that is not in the INITIALIZED state (current state: {self._state})")

        # A restored container is a new instance with a new ID.
        self._container_id = self._generate_container_id()
        logger.info(f"GVISOR ({self.sandbox_id}): Restoring to new container '{self._container_id}' from {checkpoint_path}")
        try:
            if self._config.network == "sandbox":
                await self._setup_network()
                
            self._prepare_bundle()
            cmd = self._build_runsc_cmd(
                "restore",
                f"--image-path={checkpoint_path}",
                "--bundle", self._bundle_dir,
                self._container_id
            )
            self._main_process = await self._start_main_process(cmd, "restore")
            self._state = SandboxState.RUNNING
            logger.info(f"GVISOR ({self.sandbox_id}): Restored successfully.")
        except Exception as e:
            logger.info(f"GVISOR ({self.sandbox_id}): Failed to restore: {e}")
            self._state = SandboxState.FAILED
            await self.delete()
            raise SandboxCreationError(f"Failed to restore gVisor container: {e}")
    
    async def snapshot_filesystem(self, snapshot_path: str) -> None:
        """
        Creates a snapshot of the sandbox's filesystem using 'runsc tar'.
        """
        if self._state != SandboxState.RUNNING:
            raise SandboxOperationError(f"Cannot snapshot a sandbox that is not in the RUNNING state (current state: {self._state})")

        logger.info(f"GVISOR ({self.sandbox_id}): Snapshotting filesystem to {snapshot_path}")
        try:
            cmd = self._build_runsc_cmd("tar", "rootfs-upper", f"--file={snapshot_path}", self._container_id)
            await self._run_sync_command(cmd)
            logger.info(f"GVISOR ({self.sandbox_id}): Filesystem snapshot successful.")
        except SandboxOperationError as e:
            raise SandboxSnapshotFilesystemError(f"Failed to snapshot filesystem: {e}") from e
