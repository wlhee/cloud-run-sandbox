import asyncio
import json
from typing import AsyncIterator
from websockets.exceptions import ConnectionClosed

from .types import MessageKey, EventType, SandboxEvent
from .exceptions import SandboxException, SandboxExecutionError, SandboxConnectionError

class SandboxStream:
    """
    An asynchronous iterator for the output stream of a sandbox process.
    """
    def __init__(self):
        self._queue = asyncio.Queue()

    async def __aiter__(self) -> AsyncIterator[str]:
        """Allows iterating over the stream line by line."""
        while True:
            item = await self._queue.get()
            if item is None:  # Sentinel for stream end
                break
            yield item

    async def read_all(self) -> str:
        """Reads the entire stream until EOF and returns it as a single string."""
        return "".join([item async for item in self])

    def _put(self, item):
        self._queue.put_nowait(item)

    def _close(self):
        self._queue.put_nowait(None)

class SandboxProcess:
    """
    Represents a process running within a sandbox, providing access to its I/O streams.
    """
    def __init__(self, websocket):
        self._ws = websocket
        self.stdout = SandboxStream()
        self.stderr = SandboxStream()
        self._started_event = asyncio.Event()
        self._done_event = asyncio.Event()
        self._start_error = None
        self._listen_task = None

    async def exec(self, code: str, language: str):
        """
        Starts the execution of the process in the sandbox and waits for confirmation.

        Raises:
            SandboxExecutionError: If the execution fails to start.
            SandboxConnectionError: If the connection is lost before execution starts.
        """
        self._listen_task = asyncio.create_task(self._listen())
        
        await self._ws.send(json.dumps({
            "language": language,
            "code": code,
        }))

        # Wait for the execution to be acknowledged by the server
        await self._started_event.wait()

        if self._start_error:
            # The listen task will have already exited, so we can await it to
            # propagate any exceptions that it might have raised.
            await self._listen_task
            raise self._start_error

    async def wait(self):
        """Waits for the process to complete."""
        await self._done_event.wait()

    async def terminate(self):
        """
        Terminates the running process by canceling its listener task.
        """
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

    async def _listen(self):
        """
        Processes events from the websocket to manage the process lifecycle.
        """
        try:
            while True:
                message_str = await self._ws.recv()
                message = json.loads(message_str)
                event_type = message.get(MessageKey.EVENT)

                if event_type == EventType.STATUS_UPDATE:
                    status = message.get(MessageKey.STATUS)
                    if status == SandboxEvent.SANDBOX_EXECUTION_ERROR:
                        self._start_error = SandboxExecutionError(message.get(MessageKey.MESSAGE, "Unknown execution error"))
                        self._started_event.set()
                        break
                    if status == SandboxEvent.SANDBOX_EXECUTION_DONE:
                        break
                    if status == SandboxEvent.SANDBOX_EXECUTION_RUNNING:
                        self._started_event.set()
                    continue

                if event_type == EventType.STDOUT:
                    self.stdout._put(message.get(MessageKey.DATA))
                    continue
                
                if event_type == EventType.STDERR:
                    self.stderr._put(message.get(MessageKey.DATA))
                    continue
        
        except (ConnectionClosed, asyncio.CancelledError):
            if not self._started_event.is_set():
                self._start_error = SandboxConnectionError(f"Connection closed before execution started")
        
        finally:
            # Ensure streams are closed and all waiters are unblocked
            self.stdout._close()
            self.stderr._close()
            if not self._started_event.is_set():
                self._started_event.set()
            self._done_event.set()
