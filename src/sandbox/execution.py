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
        logger.info(f"Execution created for process {self._process.pid}")

    @property
    def is_running(self):
        """Returns True if the execution process is still running."""
        return self._process.returncode is None

    async def start_streaming(self):
        """Starts the background task that streams output from the process."""
        if not self._streaming_task:
            logger.info(f"Starting streaming task for process {self._process.pid}")
            self._streaming_task = asyncio.create_task(self._stream_output())

    async def stop(self):
        """Stops the execution and cleans up resources."""
        logger.info(f"Stopping execution for process {self._process.pid}")
        if self._streaming_task:
            self._streaming_task.cancel()
            self._streaming_task = None
        
        if self.is_running:
            self._process.kill()
            await self._process.wait()
        logger.info(f"Execution stopped for process {self._process.pid}")

    async def connect(self):
        """Connects a client to the output stream."""
        q = asyncio.Queue()
        self._listener_queues.append(q)
        logger.info(f"New listener connected for process {self._process.pid}. Total listeners: {len(self._listener_queues)}")
        
        try:
            while True:
                event = await q.get()
                if isinstance(event, SandboxStreamClosed):
                    logger.info(f"SandboxStreamClosed received for process {self._process.pid}. Closing listener.")
                    raise event
                yield event
        finally:
            if q in self._listener_queues:
                self._listener_queues.remove(q)
            logger.info(f"Listener disconnected for process {self._process.pid}. Total listeners: {len(self._listener_queues)}")

    async def _stream_output(self):
        """
        Reads from the stdout and stderr of the process and broadcasts
        the output to all connected listeners.
        """
        async def broadcast(stream, stream_type):
            async for line in stream:
                event = SandboxOutputEvent(type=stream_type, data=line.decode('utf-8'))
                logger.debug(f"Broadcasting event for process {self._process.pid}: {event}")
                for queue in self._listener_queues:
                    await queue.put(event)

        try:
            logger.info(f"Starting to gather output for process {self._process.pid}")
            await asyncio.gather(
                broadcast(self._process.stdout, OutputType.STDOUT),
                broadcast(self._process.stderr, OutputType.STDERR),
                self._process.wait()
            )
            logger.info(f"Finished gathering output for process {self._process.pid}. Exit code: {self._process.returncode}")
        except Exception as e:
            logger.error(f"Error in _stream_output for process {self._process.pid}: {e}", exc_info=True)
        finally:
            logger.info(f"Broadcasting SandboxStreamClosed to all listeners for process {self._process.pid}")
            for queue in self._listener_queues:
                await queue.put(SandboxStreamClosed())
