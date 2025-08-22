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
        cmd.extend(args)
        return cmd

    async def create(self):
        """
        Creates the gVisor sandbox bundle directory and a placeholder config.
        The container itself is not created until start() is called.
        """
        try:
            print(f"[{self.sandbox_id}] Creating bundle directory: {self._bundle_dir}")
            os.makedirs(self._bundle_dir, exist_ok=True)
            print(f"[{self.sandbox_id}] Bundle directory created.")

            # The sandbox code will be mounted into the container at this path.
            sandbox_code_path = "/sandbox_code"

            config = {
                "ociVersion": "1.0.0",
                "process": { "user": {"uid": 0, "gid": 0}, "args": [], "env": [], "cwd": "/" },
                "root": {"path": "/", "readonly": True},
                "hostname": "runsc",
                "mounts": [
                    {"destination": "/proc", "type": "proc", "source": "proc"},
                    {"destination": "/dev", "type": "tmpfs", "source": "tmpfs"},
                    {"destination": "/sys", "type": "sysfs", "source": "sysfs"},
                    {
                        "destination": sandbox_code_path,
                        "type": "bind",
                        "source": self._bundle_dir,
                        "options": ["rbind", "ro"]
                    }
                ],
                "linux": { "namespaces": [{"type": "pid"}, {"type": "ipc"}, {"type": "uts"}, {"type": "mount"}] }
            }

            config_path = os.path.join(self._bundle_dir, "config.json")
            print(f"[{self.sandbox_id}] Writing OCI config to: {config_path}")
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)
            print(f"[{self.sandbox_id}] OCI config written.")
        except Exception as e:
            print(f"[{self.sandbox_id}] Error creating gVisor bundle: {e}")
            raise SandboxCreationError(f"Failed to create gVisor bundle: {e}")

    async def start(self, code: str):
        """
        Creates and starts the user's code in the sandbox and begins streaming.
        """
        try:
            # Write the user's code to a file in the bundle directory.
            temp_filepath = os.path.join(self._bundle_dir, "main.py")
            print(f"[{self.sandbox_id}] Writing code to: {temp_filepath}")
            with open(temp_filepath, "w") as f:
                f.write(code)
            print(f"[{self.sandbox_id}] Code written.")

            # Update the OCI config to execute the user's code.
            config_path = os.path.join(self._bundle_dir, "config.json")
            print(f"[{self.sandbox_id}] Updating OCI config for execution.")
            with open(config_path, "r+") as f:
                config = json.load(f)
                # The sandbox code path is defined in the create() method.
                sandbox_code_path = config["mounts"][3]["destination"]
                config["process"]["args"] = ["python3", f"{sandbox_code_path}/main.py"]
                f.seek(0)
                json.dump(config, f, indent=4)
                f.truncate()
            print(f"[{self.sandbox_id}] OCI config updated.")

            # Print the config for debugging
            with open(config_path, "r") as f:
                print(f"[{self.sandbox_id}] --- config.json ---")
                print(f.read())
                print(f"[{self.sandbox_id}] --- end config.json ---")

            # Create the container now that the config is complete.
            create_cmd = self._build_runsc_cmd("create", "--bundle", self._bundle_dir, self.sandbox_id)
            print(f"[{self.sandbox_id}] Executing runsc create: {' '.join(create_cmd)}")
            proc = await asyncio.create_subprocess_exec(
                *create_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr_bytes = await proc.communicate()
            print(f"[{self.sandbox_id}] runsc create finished with exit code {proc.returncode}.")

            if proc.returncode != 0:
                stderr = stderr_bytes.decode('utf-8')
                print(f"[{self.sandbox_id}] Failed to create gVisor container: {stderr}")
                # This is a SandboxStartError because creation is part of the start lifecycle
                raise SandboxStartError(f"Failed to create gVisor container: {stderr}")

            # 'runsc start' begins the process in the already-created container.
            start_cmd = self._build_runsc_cmd("start", self.sandbox_id)
            print(f"[{self.sandbox_id}] Executing runsc start: {' '.join(start_cmd)}")
            self._proc = await asyncio.create_subprocess_exec(
                *start_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            print(f"[{self.sandbox_id}] runsc start process initiated.")
            # Immediately start the task to stream output. No health checks needed.
            self._streaming_task = asyncio.create_task(self._stream_output_and_wait())

        except Exception as e:
            print(f"[{self.sandbox_id}] Error starting gVisor container: {e}")
            if not isinstance(e, SandboxStartError):
                 raise SandboxStartError(f"Failed to start gVisor container: {e}")
            else:
                raise e

    async def _stream_output_and_wait(self):
        """
        Reads all output from the sandbox process, waits for it to exit,
        and then broadcasts the stream closed signal.
        """
        print(f"[{self.sandbox_id}] Starting to stream output.")
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
        print(f"[{self.sandbox_id}] Output streams closed.")

        # The I/O streams from 'runsc start' have closed. Now, use 'runsc wait'
        # to deterministically wait for the container to fully terminate.
        wait_cmd = self._build_runsc_cmd("wait", self.sandbox_id)
        print(f"[{self.sandbox_id}] Executing runsc wait: {' '.join(wait_cmd)}")
        wait_proc = await asyncio.create_subprocess_exec(*wait_cmd)
        await wait_proc.wait()
        print(f"[{self.sandbox_id}] runsc wait finished.")

        # Now, signal the end of the stream to all listeners.
        for queue in self._listener_queues:
            await queue.put(SandboxStreamClosed())
        print(f"[{self.sandbox_id}] Stream closed signal sent.")

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
