import asyncio
import os
import json
import shutil
from dataclasses import dataclass, field
from .interface import SandboxInterface, SandboxCreationError, SandboxStartError, SandboxStreamClosed
from .events import SandboxOutputEvent, OutputType

@dataclass
class GVisorConfig:
    """Configuration for the GVisorSandbox."""
    use_sudo: bool = True
    rootless: bool = False
    root_dir: str = None
    bundle_dir_base: str = "/tmp"
    ignore_cgroups: bool = False
    platform: str = "ptrace"

class GVisorSandbox(SandboxInterface):
    """
    A sandbox implementation that uses gVisor ('runsc') to execute code.
    It uses the standard 'create' -> 'start' -> 'wait' lifecycle and
    manages I/O pipes manually to avoid deadlocks.
    """
    def __init__(self, sandbox_id: str, config: GVisorConfig):
        self._sandbox_id = sandbox_id
        self._config = config
        self._bundle_dir = os.path.join(config.bundle_dir_base, f"runsc_bundle_{sandbox_id}")
        self._listener_queues = []
        self._lifecycle_task = None

    @property
    def sandbox_id(self):
        return self._sandbox_id

    def _build_runsc_cmd(self, *args):
        """Builds a runsc command, adding configured flags."""
        cmd = ["runsc"]
        if self._config.use_sudo:
            cmd.insert(0, "sudo")
        if self._config.ignore_cgroups:
            cmd.append("--ignore-cgroups")
        if self._config.rootless:
            cmd.append("--rootless")
        if self._config.root_dir:
            cmd.extend(["--root", self._config.root_dir])
        if self._config.platform:
            cmd.extend(["--platform", self._config.platform])
        cmd.extend(args)
        print(f"--- Built runsc command: {' '.join(cmd)} ---")
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
        Creates the OCI bundle, creates and starts the container, and begins streaming.
        """
        self._lifecycle_task = asyncio.create_task(self._manage_lifecycle(code))

    async def _manage_lifecycle(self, code: str):
        """The core task for creating, running, and cleaning up the container."""
        r_out, w_out = -1, -1
        r_err, w_err = -1, -1
        try:
            # 1. Create pipes for stdout and stderr.
            r_out, w_out = os.pipe()
            r_err, w_err = os.pipe()

            # 2. Create the OCI bundle.
            self._create_bundle(code)

            # 3. Create the container, passing the write-ends of the pipes.
            create_cmd = self._build_runsc_cmd("create", "--bundle", self._bundle_dir, self.sandbox_id)
            create_proc = await asyncio.create_subprocess_exec(
                *create_cmd, stdout=w_out, stderr=w_err
            )
            # The parent must close its copy of the write ends.
            os.close(w_out)
            os.close(w_err)
            w_out, w_err = -1, -1 # Mark as closed

            if await create_proc.wait() != 0:
                raise SandboxStartError("runsc create failed")

            # 4. Start the container.
            start_cmd = self._build_runsc_cmd("start", self.sandbox_id)
            start_proc = await asyncio.create_subprocess_exec(*start_cmd)
            if await start_proc.wait() != 0:
                raise SandboxStartError("runsc start failed")

            # 5. Concurrently stream output and wait for the container to exit.
            stream_task = asyncio.create_task(self._stream_output(r_out, r_err))
            wait_task = asyncio.create_task(self._wait_for_exit())
            await asyncio.gather(stream_task, wait_task)

        except Exception as e:
            # Broadcast error if something fails during startup
            # This part is tricky because connect() might not be called yet.
            # For now, we rely on the exception being caught by the caller.
            print(f"Error during sandbox lifecycle: {e}")
        finally:
            # Final cleanup
            if w_out != -1: os.close(w_out)
            if w_err != -1: os.close(w_err)
            if r_out != -1: os.close(r_out)
            if r_err != -1: os.close(r_err)
            await self.delete()
            
            # Notify listeners that the stream is truly over.
            for queue in self._listener_queues:
                await queue.put(SandboxStreamClosed())

    def _create_bundle(self, code: str):
        """Helper to write the code and config.json to the bundle directory."""
        temp_filepath = os.path.join(self._bundle_dir, "main.py")
        with open(temp_filepath, "w") as f:
            f.write(code)

        sandbox_code_path = "/sandbox_code"
        config = {
            "ociVersion": "1.0.0",
            "process": {
                "user": {"uid": 0, "gid": 0},
                "args": ["python3", f"{sandbox_code_path}/main.py"],
                "env": ["PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONUNBUFFERED=1"],
                "cwd": "/"
            },
            "root": {"path": "/", "readonly": True},
            "mounts": [
                {"destination": "/proc", "type": "proc", "source": "proc"},
                {
                    "destination": sandbox_code_path, "type": "bind",
                    "source": self._bundle_dir, "options": ["rbind", "ro"]
                }
            ]
        }
        config_path = os.path.join(self._bundle_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)

    async def _stream_output(self, r_out, r_err):
        """Reads from the pipe readers and broadcasts events."""
        loop = asyncio.get_running_loop()
        
        async def broadcast(stream_reader, stream_type):
            while not stream_reader.at_eof():
                line = await stream_reader.readline()
                if not line:
                    break
                event = SandboxOutputEvent(type=stream_type, data=line.decode('utf-8'))
                for queue in self._listener_queues:
                    await queue.put(event)

        # Create StreamReader objects for the read-ends of the pipes
        out_reader = asyncio.StreamReader(loop=loop)
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(out_reader), os.fdopen(r_out))

        err_reader = asyncio.StreamReader(loop=loop)
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(err_reader), os.fdopen(r_err))

        await asyncio.gather(
            broadcast(out_reader, OutputType.STDOUT),
            broadcast(err_reader, OutputType.STDERR)
        )

    async def _wait_for_exit(self):
        """Runs 'runsc wait' to block until the container exits."""
        wait_cmd = self._build_runsc_cmd("wait", self.sandbox_id)
        wait_proc = await asyncio.create_subprocess_exec(*wait_cmd)
        await wait_proc.wait()

    async def connect(self):
        """Creates a new consumer queue and yields events from it."""
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
        """Stops the container using 'runsc kill'."""
        kill_cmd = self._build_runsc_cmd("kill", self.sandbox_id, "SIGKILL")
        kill_proc = await asyncio.create_subprocess_exec(*kill_cmd)
        await kill_proc.wait()

    async def delete(self):
        """Deletes the container and its bundle."""
        await self.stop()
        
        delete_cmd = self._build_runsc_cmd("delete", "--force", self.sandbox_id)
        delete_proc = await asyncio.create_subprocess_exec(*delete_cmd)
        await delete_proc.wait()

        if os.path.exists(self._bundle_dir):
            shutil.rmtree(self._bundle_dir)
