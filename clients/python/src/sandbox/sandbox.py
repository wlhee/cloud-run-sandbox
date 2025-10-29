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
import weakref
import websockets

from .types import MessageKey, EventType, SandboxEvent
from .exceptions import SandboxConnectionError, SandboxCreationError, SandboxStateError
from .process import SandboxProcess

class Sandbox:
    """
    Represents a connection to a Cloud Run Sandbox, used to execute commands.
    """
    def __init__(self, websocket, enable_debug=False, debug_label=""):
        self._ws = websocket
        self._sandbox_id = None
        self._active_process = None
        self._created_event = asyncio.Event()
        self._creation_error = None
        self._stop_event = asyncio.Event()
        self._listen_task = None
        self._state = "creating"
        self._shutdown_lock = asyncio.Lock()
        self._enable_debug = enable_debug
        self._debug_label = debug_label

    @property
    def sandbox_id(self):
        """The unique ID of the sandbox."""
        return self._sandbox_id

    @classmethod
    async def create(cls, url: str, idle_timeout: int = 60, ssl=None, enable_debug=False, debug_label=""):
        """
        Creates a new sandbox session.
        """
        instance = cls(None, enable_debug, debug_label)
        try:
            # Use __await__ to make it compatible with the AsyncMock from tests
            sanitized_url = url.rstrip('/')
            instance._log_debug(f"Connecting to {sanitized_url}/create")
            websocket = await websockets.connect(f"{sanitized_url}/create", ssl=ssl)
            instance._ws = websocket
            instance._log_debug("Connection established.")
        except websockets.exceptions.InvalidURI as e:
            raise SandboxConnectionError(f"Invalid WebSocket URI: {e}")
        except ConnectionRefusedError:
            raise SandboxConnectionError(f"Connection refused for WebSocket URI: {url}")

        await instance._send({"idle_timeout": idle_timeout})
        
        instance._listen_task = asyncio.create_task(instance._listen())
        await instance._wait_for_creation()
        return instance

    def _log_debug(self, message):
        if self._enable_debug:
            label = f"[{self._debug_label}]" if self._debug_label else ""
            print(f"{label} {message}")

    async def _send(self, data: dict):
        """Sends a JSON message to the WebSocket."""
        message_str = json.dumps(data)
        await self._ws.send(message_str)

    async def _wait_for_creation(self):
        """
        Waits for the initial handshake to complete and the sandbox to be running.
        """
        await self._created_event.wait()
        if self._creation_error:
            raise self._creation_error


    async def exec(self, language: str, code: str) -> SandboxProcess:
        """
        Creates and starts a new process in the sandbox for code execution.
        """
        if self._active_process:
            raise RuntimeError("Another process is already running in this sandbox.")
        if self._state != "running":
            raise SandboxStateError(f"Sandbox is not in a running state. Current state: {self._state}")

        process = SandboxProcess(self._send, on_done=self._clear_active_process)
        self._active_process = process
        
        await process.exec(language, code)
        return process

    def _clear_active_process(self):
        self._active_process = None

    def _handle_creation_error(self, exc):
        if self._state == "creating":
            self._state = "failed"
            self._creation_error = exc
            self._created_event.set()
            self._log_debug(f"Creation failed: {exc}")

    async def _listen(self):
        """
        Listens for all incoming WebSocket messages and dispatches them.
        """
        try:
            while not self._stop_event.is_set():
                recv_task = asyncio.create_task(self._ws.recv())
                stop_task = asyncio.create_task(self._stop_event.wait())

                done, pending = await asyncio.wait(
                    [recv_task, stop_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                if stop_task in done:
                    recv_task.cancel()
                    break

                message_str = recv_task.result()
                message = json.loads(message_str)
                event = message.get(MessageKey.EVENT)

                # Handle noisy I/O events first and skip logging for them.
                if event in [EventType.STDOUT, EventType.STDERR]:
                    if self._active_process:
                        self._active_process.handle_message(message)
                    continue

                # For all other messages, log first.
                self._log_debug(f"Received message: {message_str}")

                # Now, dispatch the message.
                is_execution_status = (event == EventType.STATUS_UPDATE and
                                       message.get(MessageKey.STATUS, "").startswith("SANDBOX_EXECUTION_"))

                if is_execution_status:
                    if self._active_process:
                        self._active_process.handle_message(message)
                    continue

                # Handle sandbox lifecycle events
                if event == EventType.SANDBOX_ID:
                    self._sandbox_id = message.get(MessageKey.SANDBOX_ID)
                    continue

                if event == EventType.STATUS_UPDATE:
                    status = message.get(MessageKey.STATUS)
                    if status == SandboxEvent.SANDBOX_RUNNING:
                        self._state = "running"
                        self._created_event.set()
                    elif status == SandboxEvent.SANDBOX_CREATION_ERROR:
                        error = SandboxCreationError(message.get(MessageKey.MESSAGE, status))
                        self._handle_creation_error(error)
                        await self._shutdown()
                        break
        
        except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError) as e:
            error = SandboxConnectionError(f"Connection closed: {e}")
            self._log_debug(f"Connection closed: {e}")
            self._handle_creation_error(error)
            await self._shutdown()
        
        except Exception as e:
            self._log_debug(f"An unexpected error occurred: {e}")
            self._handle_creation_error(e)
            await self._shutdown()

    async def _shutdown(self):
        async with self._shutdown_lock:
            if self._state == "running":
                self._state = "closed"
                self._log_debug("State changed to closed")

            if self._active_process:
                await self._active_process.terminate()
                self._active_process = None

            if self._listen_task and not self._listen_task.done():
                self._stop_event.set()
                if asyncio.current_task() is not self._listen_task:
                    await self._listen_task

            if self._ws and self._ws.state != websockets.protocol.State.CLOSED:
                self._log_debug("Closing WebSocket connection.")
                await self._ws.close()

    async def terminate(self):
        """
        Terminates the sandbox session.
        """
        await self._shutdown()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.terminate()