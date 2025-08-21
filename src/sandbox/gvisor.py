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
        if self._config.rootless:
            cmd.append("--rootless")
        if self._config.root_dir:
            cmd.extend(["--root", self._config.root_dir])
        cmd.extend(args)
        return cmd

    async def create(self):
        """
        Creates the necessary bundle directory and OCI config for gVisor.
        """
        try:
            os.makedirs(self._bundle_dir, exist_ok=True)
            config = {
                "ociVersion": "1.0.0",
                "process": { "user": {"uid": 0, "gid": 0}, "args": [], "env": [], "cwd": "/" },
                "root": {"path": self._bundle_dir, "readonly": False}, # Rootfs is the bundle itself
                "hostname": "runsc",
                "mounts": [
                    {"destination": "/proc", "type": "proc", "source": "proc"},
                    {"destination": "/dev", "type": "tmpfs", "source": "tmpfs"},
                    {"destination": "/sys", "type": "sysfs", "source": "sysfs"},
                ],
                "linux": { "namespaces": [{"type": "pid"}, {"type": "network"}, {"type": "ipc"}, {"type": "uts"}, {"type": "mount"}] }
            }
            with open(os.path.join(self._bundle_dir, "config.json"), "w") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            raise SandboxCreationError(f"Failed to create gVisor bundle: {e}")

    async def start(self, code: str):
        """
        Writes the code to a file, starts the gVisor container, and begins
        the internal output streaming task.
        """
        try:
            temp_filepath = os.path.join(self._bundle_dir, "main.py")
            with open(temp_filepath, "w") as f:
                f.write(code)

            config_path = os.path.join(self._bundle_dir, "config.json")
            with open(config_path, "r+") as f:
                config = json.load(f)
                config["process"]["args"] = ["python3", "/main.py"] # Path is inside the container
                f.seek(0)
                json.dump(config, f, indent=4)
                f.truncate()

            run_cmd = self._build_runsc_cmd("--network=host", "run", "-bundle", self._bundle_dir, self.sandbox_id)
            self._proc = await asyncio.create_subprocess_exec(
                *run_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self._streaming_task = asyncio.create_task(self._stream_output_and_wait())
        except Exception as e:
            raise SandboxStartError(f"Failed to start gVisor container: {e}")

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
        Creates a new consumer queue, adds it to the listeners, and yields
        events from it until the stream is closed.
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
            self._listener_queues.remove(q)

    async def stop(self):
        if self._streaming_task:
            self._streaming_task.cancel()
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            await self._proc.wait()

    async def delete(self):
        await self.stop()
        if os.path.exists(self._bundle_dir):
            await asyncio.create_subprocess_exec("rm", "-rf", self._bundle_dir)
        
        delete_cmd = self._build_runsc_cmd("delete", self.sandbox_id)
        await asyncio.create_subprocess_exec(*delete_cmd)
