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
    ignore_cgroups: bool = False
    platform: str = "ptrace"

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
        if self._config.ignore_cgroups:
            cmd.append("--ignore-cgroups")
        if self._config.rootless:
            cmd.append("--rootless")
        if self._config.root_dir:
            cmd.extend(["--root", self._config.root_dir])
        if self._config.platform:
            cmd.extend(["--platform", self._config.platform])
        cmd.extend(args)
        return cmd

    async def create(self):
        """
        Creates the gVisor sandbox bundle directory.
        """
        try:
            os.makedirs(self._bundle_dir, exist_ok=True)
        except Exception as e:
            raise SandboxCreationError(f"Failed to create gVisor bundle directory: {e}")

    async def start(self, code: str):
        """
        Creates the OCI bundle and runs the code in the sandbox using 'runsc run'.
        """
        try:
            # 1. Write the user's code to a file in the bundle directory.
            temp_filepath = os.path.join(self._bundle_dir, "main.py")
            with open(temp_filepath, "w") as f:
                f.write(code)

            # 2. Create the OCI config.json.
            sandbox_code_path = "/sandbox_code"
            config = {
                "ociVersion": "1.0.0",
                "process": {
                    "user": {"uid": 0, "gid": 0},
                    "args": ["python3", f"{sandbox_code_path}/main.py"],
                    "env": [
                        "PATH=/usr/local/bin:/usr/bin:/bin",
                        "PYTHONUNBUFFERED=1"
                    ],
                    "cwd": "/"
                },
                "root": {"path": "/", "readonly": True},
                "mounts": [
                    {"destination": "/proc", "type": "proc", "source": "proc"},
                    {
                        "destination": sandbox_code_path,
                        "type": "bind",
                        "source": self._bundle_dir,
                        "options": ["rbind", "ro"]
                    }
                ]
            }
            config_path = os.path.join(self._bundle_dir, "config.json")
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)

            # 3. Execute the sandbox using 'runsc run'.
            run_cmd = self._build_runsc_cmd("run", "--bundle", self._bundle_dir, self.sandbox_id)
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
        
        await asyncio.gather(
            broadcast(self._proc.stdout, OutputType.STDOUT),
            broadcast(self._proc.stderr, OutputType.STDERR)
        )
        
        await self._proc.wait()

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
        if self._proc and self._proc.returncode is None:
            self._proc.kill()

    async def delete(self):
        await self.stop()
        if os.path.exists(self._bundle_dir):
            shutil.rmtree(self._bundle_dir)
