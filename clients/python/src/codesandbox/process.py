# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import json
from typing import AsyncIterator, Callable

from .types import MessageKey, EventType, SandboxEvent
from .exceptions import SandboxExecutionError

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
    def __init__(self, websocket, on_done: Callable[[], None] = None):
        self._ws = websocket
        self.stdout = SandboxStream()
        self.stderr = SandboxStream()
        self._started_event = asyncio.Event()
        self._done_event = asyncio.Event()
        self._start_error = None
        self._on_done = on_done

    def _set_done(self):
        """
        Marks the process as done, cleans up resources, and notifies listeners.
        This method is idempotent.
        """
        if self._done_event.is_set():
            return
        
        self._cleanup()
        if self._on_done:
            self._on_done()
        
        # This must be the last step, as it unblocks awaiters.
        self._done_event.set()

    def handle_message(self, message: dict):
        """
        Processes a message from the WebSocket and updates the process state.
        """
        if self._done_event.is_set():
            return

        event_type = message.get(MessageKey.EVENT)

        if event_type == EventType.STATUS_UPDATE:
            status = message.get(MessageKey.STATUS)
            if status == SandboxEvent.SANDBOX_EXECUTION_RUNNING:
                self._started_event.set()
            elif status == SandboxEvent.SANDBOX_EXECUTION_ERROR:
                self._start_error = SandboxExecutionError(message.get(MessageKey.MESSAGE, "Unknown execution error"))
                self._started_event.set()
                self._set_done() # An error means the process is done.
            elif status == SandboxEvent.SANDBOX_EXECUTION_DONE:
                self._set_done()
            return

        if event_type == EventType.STDOUT:
            self.stdout._put(message.get(MessageKey.DATA))
            return
        
        if event_type == EventType.STDERR:
            self.stderr._put(message.get(MessageKey.DATA))
            return

    async def exec(self, language: str, code: str):
        """
        Starts the execution of the process in the sandbox and waits for confirmation.

        Raises:
            SandboxExecutionError: If the execution fails to start.
        """
        await self._ws.send(json.dumps({
            "language": language,
            "code": code,
        }))

        # Wait for the execution to be acknowledged by the server
        await self._started_event.wait()

        if self._start_error:
            raise self._start_error

    async def wait(self):
        """Waits for the process to complete."""
        await self._done_event.wait()

    async def write_to_stdin(self, data: str):
        """Writes data to the stdin of the process."""
        await self._ws.send(json.dumps({
            "event": "stdin",
            "data": data,
        }))

    async def terminate(self):
        """
        Terminates the running process.
        """
        self._set_done()

    def _cleanup(self):
        """
        Cleans up resources used by the process.
        """
        self.stdout._close()
        self.stderr._close()
