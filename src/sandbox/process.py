import asyncio
import logging
from typing import AsyncGenerator, List

logger = logging.getLogger(__name__)

class Process:
    """
    A wrapper around an asyncio subprocess that provides a consistent interface
    for creating, streaming output from, and managing the process lifecycle.

    This implementation uses background tasks to continuously drain the stdout and
    stderr pipes into internal queues, preventing deadlocks that can occur if
    a consumer only reads from one stream while the other's buffer fills up.
    """
    def __init__(self, cmd: List[str]):
        self._cmd = cmd
        self._process: asyncio.subprocess.Process = None
        self._stdout_queue = asyncio.Queue()
        self._stderr_queue = asyncio.Queue()
        self._stream_tasks = []

    @property
    def is_running(self) -> bool:
        """Returns True if the process has been started and has not exited."""
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        """Starts the process and begins draining its output streams."""
        if self._process:
            raise RuntimeError("Process has already been started.")
        
        self._process = await asyncio.create_subprocess_exec(
            *self._cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Start background tasks to drain the pipes immediately.
        self._stream_tasks.append(
            asyncio.create_task(self._drain_pipe(self._process.stdout, self._stdout_queue))
        )
        self._stream_tasks.append(
            asyncio.create_task(self._drain_pipe(self._process.stderr, self._stderr_queue))
        )

    async def _drain_pipe(self, pipe, queue: asyncio.Queue):
        """Reads from a pipe and pushes raw decoded strings to a queue."""
        try:
            while not pipe.at_eof():
                data = await pipe.read(1024)
                if data:
                    await queue.put(data.decode("utf-8"))
        except Exception as e:
            logger.debug(f"Pipe draining ended: {e}")
        finally:
            await queue.put(None) # Signal EOF for this stream

    async def stream_stdout(self) -> AsyncGenerator[str, None]:
        """Yields strings from the process's stdout stream."""
        async for data in self._stream_from_queue(self._stdout_queue):
            yield data

    async def stream_stderr(self) -> AsyncGenerator[str, None]:
        """Yields strings from the process's stderr stream."""
        async for data in self._stream_from_queue(self._stderr_queue):
            yield data

    async def _stream_from_queue(self, queue: asyncio.Queue) -> AsyncGenerator[str, None]:
        """A helper to yield strings from a queue until a None sentinel is received."""
        if not self._process:
            raise RuntimeError("Process has not been started yet.")
        
        while True:
            data = await queue.get()
            if data is None:
                break
            yield data

    async def write_to_stdin(self, data: str) -> None:
        """Writes data to the process's stdin."""
        if self.is_running and self._process.stdin:
            self._process.stdin.write(data.encode("utf-8"))
            await self._process.stdin.drain()

    async def wait(self) -> int:
        """Waits for the process to terminate and returns its exit code."""
        if not self._process:
            raise RuntimeError("Process has not been started yet.")
        return await self._process.wait()

    async def stop(self) -> None:
        """Stops the process and cancels the stream draining tasks."""
        if self.is_running:
            self._process.terminate()
            await self._process.wait()
        
        for task in self._stream_tasks:
            task.cancel()
        self._stream_tasks.clear()
