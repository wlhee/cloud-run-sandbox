import asyncio
from .types import SandboxOutputEvent, OutputType
from .interface import SandboxStreamClosed
import logging

logger = logging.getLogger(__name__)

class Execution:
    """
    Manages the lifecycle of a single code execution, including its
    process and streaming task.
    """
    def __init__(self, process: asyncio.subprocess.Process):
        self._process = process
        self._streaming_task = None
        self._listener_queues = []
        print(f">>> [EXECUTION] Created for process {self._process.pid}")

    @property
    def is_running(self):
        """Returns True if the execution process is still running."""
        return self._process.returncode is None

    async def start_streaming(self):
        """Starts the background task that streams output from the process."""
        if not self._streaming_task:
            print(f">>> [EXECUTION] Starting streaming task for process {self._process.pid}")
            self._streaming_task = asyncio.create_task(self._stream_output())

    async def stop(self):
        """Stops the execution and cleans up resources."""
        print(f">>> [EXECUTION] Stopping execution for process {self._process.pid}")
        if self._streaming_task:
            self._streaming_task.cancel()
            self._streaming_task = None
        
        if self.is_running:
            self._process.kill()
            await self._process.wait()
        print(f">>> [EXECUTION] Execution stopped for process {self._process.pid}")

    async def connect(self):
        """Connects a client to the output stream."""
        q = asyncio.Queue()
        self._listener_queues.append(q)
        print(f">>> [EXECUTION] New listener connected for process {self._process.pid}. Total listeners: {len(self._listener_queues)}")
        
        try:
            while True:
                event = await q.get()
                if isinstance(event, SandboxStreamClosed):
                    print(f">>> [EXECUTION] SandboxStreamClosed received for process {self._process.pid}. Closing listener.")
                    raise event
                yield event
        finally:
            if q in self._listener_queues:
                self._listener_queues.remove(q)
            print(f">>> [EXECUTION] Listener disconnected for process {self._process.pid}. Total listeners: {len(self._listener_queues)}")

    async def _stream_output(self):
        """
        Reads from the stdout and stderr of the process and broadcasts
        the output to all connected listeners.
        """
        async def broadcast(stream, stream_type):
            async for line in stream:
                event = SandboxOutputEvent(type=stream_type, data=line.decode('utf-8'))
                print(f">>> [EXECUTION] Broadcasting event for process {self._process.pid}: {event}")
                for queue in self._listener_queues:
                    await queue.put(event)

        try:
            print(f">>> [EXECUTION] Starting to gather output for process {self._process.pid}")
            await asyncio.gather(
                broadcast(self._process.stdout, OutputType.STDOUT),
                broadcast(self._process.stderr, OutputType.STDERR),
                self._process.wait()
            )
            print(f">>> [EXECUTION] Finished gathering output for process {self._process.pid}. Exit code: {self._process.returncode}")
        except Exception as e:
            print(f">>> [EXECUTION] Error in _stream_output for process {self._process.pid}: {e}")
        finally:
            print(f">>> [EXECUTION] Broadcasting SandboxStreamClosed to all listeners for process {self._process.pid}")
            for queue in self._listener_queues:
                await queue.put(SandboxStreamClosed())
