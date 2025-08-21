import asyncio
import os
import json
from dataclasses import dataclass, field
from .interface import SandboxInterface, SandboxCreationError, SandboxStartError, SandboxStreamClosed
from .events import SandboxOutputEvent, OutputType

@dataclass
class GVisorConfig:
    """Configuration for the GVisorSandbox."""
    rootless: bool = False
    root_dir: str = None
    bundle_dir_base: str = "/tmp"
    systemd_cgroup: bool = False

class GVisorSandbox(SandboxInterface):
    """
    A sandbox implementation that uses gVisor ('runsc') to execute code.
    It uses an in-memory broadcast pattern to allow clients to connect and
    stream new output.
    """
    def __init__(self, sandbox_id: str, config: GVisorConfig):
        self._sandbox_id = sandbox_id
        self._config = config
        self._bundle_dir = os.path.join(config.bundle_dir_base, f"runsc_bundle_{sandbox_id}")
        self._proc = None
        self._listener_queues = []
        self._streaming_task = None

    @property
    def sandbox_id(self):
        return self._sandbox_id

    def _build_runsc_cmd(self, *args):
        """Builds a runsc command, adding configured flags."""
        cmd = ["runsc"]
        if self._config.systemd_cgroup:
            cmd.append("--systemd-cgroup")
        if self._config.rootless:
            cmd.append("--rootless")
        if self._config.root_dir:
            cmd.extend(["--root", self._config.root_dir])
        cmd.extend(args)
        return cmd

    async def create(self):
        """
        Creates the gVisor sandbox bundle directory and a placeholder config.
        The container itself is not created until start() is called.
        """
        try:
            os.makedirs(self._bundle_dir, exist_ok=True)
            config = {
                "ociVersion": "1.0.0",
                "process": { "user": {"uid": 0, "gid": 0}, "args": [], "env": [], "cwd": "/" },
                "root": {"path": self._bundle_dir, "readonly": False},
                "hostname": "runsc",
                "mounts": [
                    {"destination": "/proc", "type": "proc", "source": "proc"},
                    {"destination": "/dev", "type": "tmpfs", "source": "tmpfs"},
                    {"destination": "/sys", "type": "sysfs", "source": "sysfs"},
                ],
                "linux": { "namespaces": [{"type": "pid"}, {"type": "ipc"}, {"type": "uts"}, {"type": "mount"}] }
            }
            if self._config.systemd_cgroup:
                config["linux"]["cgroupsPath"] = f"machine.slice/machine-{self.sandbox_id}.scope"

            with open(os.path.join(self._bundle_dir, "config.json"), "w") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            raise SandboxCreationError(f"Failed to create gVisor bundle: {e}")

    async def start(self, code: str):
        """
        Creates and starts the user's code in the sandbox and begins streaming.
        """
        try:
            # Write the user's code to a file in the bundle directory.
            temp_filepath = os.path.join(self._bundle_dir, "main.py")
            with open(temp_filepath, "w") as f:
                f.write(code)

            # Update the OCI config to execute the user's code.
            config_path = os.path.join(self._bundle_dir, "config.json")
            with open(config_path, "r+") as f:
                config = json.load(f)
                config["process"]["args"] = ["python3", "/main.py"]
                f.seek(0)
                json.dump(config, f, indent=4)
                f.truncate()

            # Create the container now that the config is complete.
            create_cmd = self._build_runsc_cmd("create", "--bundle", self._bundle_dir, self.sandbox_id)
            proc = await asyncio.create_subprocess_exec(
                *create_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr_bytes = await proc.communicate()

            if proc.returncode != 0:
                # This is a SandboxStartError because creation is part of the start lifecycle
                raise SandboxStartError(f"Failed to create gVisor container: {stderr_bytes.decode('utf-8')}")

            # 'runsc start' begins the process in the already-created container.
            start_cmd = self._build_runsc_cmd("start", self.sandbox_id)
            self._proc = await asyncio.create_subprocess_exec(
                *start_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            # Immediately start the task to stream output. No health checks needed.
            self._streaming_task = asyncio.create_task(self._stream_output_and_wait())

        except Exception as e:
            if not isinstance(e, SandboxStartError):
                 raise SandboxStartError(f"Failed to start gVisor container: {e}")
            else:
                raise e

    async def _stream_output_and_wait(self):
        """
        Reads all output from the sandbox process, waits for it to exit,
        and then broadcasts the stream closed signal.
        """
        async def broadcast(stream, stream_type):
            while True:
                line = await stream.readline()
                if not line:
                    break
                event = SandboxOutputEvent(type=stream_type, data=line.decode('utf-8'))
                for queue in self._listener_queues:
                    await queue.put(event)
        
        # Concurrently read stdout and stderr until both are closed.
        await asyncio.gather(
            broadcast(self._proc.stdout, OutputType.STDOUT),
            broadcast(self._proc.stderr, OutputType.STDERR)
        )

        # The I/O streams from 'runsc start' have closed. Now, use 'runsc wait'
        # to deterministically wait for the container to fully terminate.
        wait_proc = await asyncio.create_subprocess_exec(*self._build_runsc_cmd("wait", self.sandbox_id))
        await wait_proc.wait()

        # Now, signal the end of the stream to all listeners.
        for queue in self._listener_queues:
            await queue.put(SandboxStreamClosed())

    async def connect(self):
        """
        Creates a new consumer queue and yields events from it.
        """
        q = asyncio.Queue()
        self._listener_queues.append(q)
        try:
            while True:
                event = await q.get()
                if isinstance(event, SandboxStreamClosed):
                    raise event
                yield event
        finally:
            if q in self._listener_queues:
                self._listener_queues.remove(q)

    async def stop(self):
        if self._streaming_task:
            self._streaming_task.cancel()
        if self._proc and self._proc.returncode is None:
            # Use 'runsc kill' for a more forceful stop, then clean up.
            kill_cmd = self._build_runsc_cmd("kill", self.sandbox_id, "SIGKILL")
            proc = await asyncio.create_subprocess_exec(*kill_cmd)
            await proc.wait()

    async def delete(self):
        await self.stop()
        
        # Use --force to ensure cleanup even if the container is stopped.
        delete_cmd = self._build_runsc_cmd("delete", "--force", self.sandbox_id)
        proc = await asyncio.create_subprocess_exec(*delete_cmd)
        await proc.wait()

        # Clean up the bundle directory on the host.
        if os.path.exists(self._bundle_dir):
            # Use a subprocess for 'rm -rf' to avoid issues with complex permissions.
            await asyncio.create_subprocess_exec("rm", "-rf", self._bundle_dir)
