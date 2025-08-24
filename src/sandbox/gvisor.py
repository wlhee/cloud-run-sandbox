import asyncio
import os
import json
import shutil
import tempfile
from dataclasses import dataclass
from .interface import SandboxInterface, SandboxCreationError, SandboxStartError, SandboxStreamClosed
from .events import SandboxOutputEvent, OutputType

@dataclass
class GVisorConfig:
    """Configuration for the GVisorSandbox."""
    use_sudo: bool = False
    rootless: bool = False
    # root_dir is now an optional base path. A unique dir will be created inside it.
    root_dir_base: str = "/tmp"
    bundle_dir_base: str = "/tmp"
    ignore_cgroups: bool = False
    platform: str = "ptrace"

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
        self._exec_proc = None
        self._listener_queues = []
        self._streaming_task = None

    @property
    def sandbox_id(self):
        return self._sandbox_id

    def _build_runsc_cmd(self, *args):
        """Builds a runsc command, adding configured flags."""
        cmd = ["runsc"]
        if self._config.use_sudo:
            cmd.insert(0, "sudo")
        # Always use the unique root directory.
        cmd.extend([f"--root={self._root_dir}"])
        if self._config.rootless:
            cmd.append("--rootless")
        if self._config.ignore_cgroups:
            cmd.append("--ignore-cgroups")
        if self._config.platform:
            cmd.extend(["--platform", self._config.platform])
        cmd.extend(args)
        return cmd

    async def _run_sync_command(self, cmd, check=True):
        """Helper to run a synchronous command."""
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        if check and proc.returncode != 0:
            raise SandboxStartError(f"Command failed: {' '.join(cmd)}
{stderr.decode()}")
        return stdout.decode(), stderr.decode()

    async def create(self):
        """
        Creates the OCI bundle and starts a long-running, detached container.
        """
        try:
            os.makedirs(self._bundle_dir, exist_ok=True)
            
            # 1. Create the OCI bundle for a long-running process.
            config = {
                "ociVersion": "1.0.0",
                "process": {"user": {"uid": 0, "gid": 0}, "args": ["sh", "-c", "while true; do sleep 3600; done"]},
                "root": {"path": "/", "readonly": True},
                "mounts": [{"destination": "/proc", "type": "proc", "source": "proc"}]
            }
            config_path = os.path.join(self._bundle_dir, "config.json")
            with open(config_path, "w") as f:
                json.dump(config, f)

            # 2. Start the container in detached mode.
            run_cmd = self._build_runsc_cmd("run", "--detach", "--bundle", self._bundle_dir, self.sandbox_id)
            await self._run_sync_command(run_cmd)

        except Exception as e:
            await self.delete()
            raise SandboxCreationError(f"Failed to create gVisor container: {e}")

    async def start(self, code: str):
        pass

    async def stop(self):
        """Stops the container using 'runsc kill'."""
        kill_cmd = self._build_runsc_cmd("kill", self.sandbox_id, "SIGKILL")
        await self._run_sync_command(kill_cmd, check=False)

    async def delete(self):
        """Deletes the container and its bundle."""
        await self.stop()
        
        delete_cmd = self._build_runsc_cmd("delete", "--force", self.sandbox_id)
        await self._run_sync_command(delete_cmd, check=False)

        if os.path.exists(self._bundle_dir):
            shutil.rmtree(self._bundle_dir)
        if os.path.exists(self._root_dir):
            shutil.rmtree(self._root_dir)

    async def connect(self):
        if False:
            yield
