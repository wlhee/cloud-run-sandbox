import asyncio
from .types import SandboxOutputEvent, OutputType
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
        self._output_queue = asyncio.Queue()

    @property
    def is_running(self):
        """Returns True if the execution process is still running."""
        return self._streaming_task and not self._streaming_task.done()

    async def start_streaming(self):
        """Starts the background task that streams output from the process."""
        if not self._streaming_task:
            self._streaming_task = asyncio.create_task(self._stream_output())

    async def stop(self):
        """Stops the execution and cleans up resources."""
        if self._streaming_task:
            self._streaming_task.cancel()
            self._streaming_task = None
        
        if self._process.returncode is None:
            self._process.kill()
            await self._process.wait()

    async def connect(self):
        """Yields events from the output queue until the stream is closed."""
        while True:
            event = await self._output_queue.get()
            if event is None:  # Sentinel value indicates the end of the stream.
                break
            yield event

    async def wait(self):
        """Waits for the streaming to finish and the process to exit."""
        if self._streaming_task:
            await self._streaming_task
        await self._process.wait()

    async def _stream_output(self):
        """
        Reads from the stdout and stderr of the process and puts events
        into the output queue.
        """
        async def stream_pipe(stream, stream_type):
            async for line in stream:
                event = SandboxOutputEvent(type=stream_type, data=line.decode('utf-8'))
                await self._output_queue.put(event)

        try:
            await asyncio.gather(
                stream_pipe(self._process.stdout, OutputType.STDOUT),
                stream_pipe(self._process.stderr, OutputType.STDERR)
            )
        finally:
            await self._output_queue.put(None)  # Sentinel to signal end of stream
