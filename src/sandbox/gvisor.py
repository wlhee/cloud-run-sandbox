import asyncio
import os
import json
from .interface import SandboxInterface, SandboxCreationError, SandboxStartError
from .events import SandboxOutputEvent, OutputType

class GVisorSandbox(SandboxInterface):
    """
    A sandbox implementation that uses gVisor ('runsc') to execute code.
    It uses an in-memory broadcast pattern to allow clients to connect and
    stream new output.
    """
    def __init__(self, sandbox_id):
        self._sandbox_id = sandbox_id
        self._bundle_dir = f"/tmp/runsc_bundle_{sandbox_id}"
        self._proc = None
        self._listener_queues = []
        self._streaming_task = None

    @property
    def sandbox_id(self):
        return self._sandbox_id

    async def create(self):
        """
        Creates the necessary bundle directory and OCI config for gVisor.
        """
        try:
            os.makedirs(self._bundle_dir, exist_ok=True)
            config = {
                "ociVersion": "1.0.0",
                "process": { "user": {"uid": 0, "gid": 0}, "args": [], "env": [], "cwd": "/" },
                "root": {"path": "/", "readonly": False},
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
                config["process"]["args"] = ["python3", temp_filepath]
                f.seek(0)
                json.dump(config, f, indent=4)
                f.truncate()

            run_cmd = ["runsc", "--network=host", "run", "-bundle", self._bundle_dir, self.sandbox_id]
            self._proc = await asyncio.create_subprocess_exec(
                *run_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self._streaming_task = asyncio.create_task(self._stream_and_broadcast_output())
        except Exception as e:
            raise SandboxStartError(f"Failed to start gVisor container: {e}")

    async def _stream_and_broadcast_output(self):
        """
        The single producer task that reads from the sandbox process and
        broadcasts the output to all listener queues.
        """
        async def broadcast(stream, stream_type):
            while True:
                line = await stream.readline()
                if not line:
                    break
                event = SandboxOutputEvent(type=stream_type, data=line.decode('utf-8'))
                for queue in self._listener_queues:
                    await queue.put(event)
        
        await asyncio.gather(
            broadcast(self._proc.stdout, OutputType.STDOUT),
            broadcast(self._proc.stderr, OutputType.STDERR)
        )

    async def connect(self):
        """
        Creates a new consumer queue, adds it to the listeners, and yields
        events from it.
        """
        q = asyncio.Queue()
        self._listener_queues.append(q)
        try:
            while True:
                yield await q.get()
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
        await asyncio.create_subprocess_exec("runsc", "delete", self.sandbox_id)