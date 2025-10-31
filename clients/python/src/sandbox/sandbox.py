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
from .exceptions import SandboxConnectionError, SandboxCreationError, SandboxStateError, SandboxFilesystemSnapshotError
from .process import SandboxProcess

class Sandbox:
    """
    Represents a connection to a Cloud Run Sandbox, used to execute commands.
    """
    def __init__(self, websocket, initial_state: str, enable_debug=False, debug_label=""):
        self._ws = websocket
        self._sandbox_id = None
        self._active_process = None
        self._ready_event = asyncio.Event()
        self._killed_event = asyncio.Event()
        self._filesystem_snapshot_event = asyncio.Event()
        self._filesystem_snapshot_error = None
        self._error_on_ready = None
        self._stop_event = asyncio.Event()
        self._listen_task = None
        self._state = initial_state
        self._shutdown_lock = asyncio.Lock()
        self._enable_debug = enable_debug
        self._debug_label = debug_label
        self._is_kill_intentionally = False

    @property
    def sandbox_id(self):
        """The unique ID of the sandbox."""
        return self._sandbox_id

    @classmethod
    async def create(cls, url: str, idle_timeout: int = 60, ssl=None, enable_debug=False, debug_label="", filesystem_snapshot_name: str = None):
        """
        Creates a new sandbox session.
        """
        instance = cls(None, "creating", enable_debug, debug_label)
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

        create_params = {"idle_timeout": idle_timeout}
        if filesystem_snapshot_name:
            create_params["filesystem_snapshot_name"] = filesystem_snapshot_name
        await instance._send(create_params)
        
        instance._listen_task = asyncio.create_task(instance._listen())
        await instance._wait_for_ready()
        return instance

    @classmethod
    async def attach(cls, url: str, sandbox_id: str, ssl=None, enable_debug=False, debug_label=""):
        """
        Attaches to an existing sandbox session.
        """
        instance = cls(None, "attaching", enable_debug, debug_label)
        try:
            sanitized_url = url.rstrip('/')
            instance._log_debug(f"Connecting to {sanitized_url}/attach/{sandbox_id}")
            websocket = await websockets.connect(f"{sanitized_url}/attach/{sandbox_id}", ssl=ssl)
            instance._ws = websocket
            instance._sandbox_id = sandbox_id
            instance._log_debug("Connection established.")
        except websockets.exceptions.InvalidURI as e:
            raise SandboxConnectionError(f"Invalid WebSocket URI: {e}")
        except ConnectionRefusedError:
            raise SandboxConnectionError(f"Connection refused for WebSocket URI: {url}")

        instance._listen_task = asyncio.create_task(instance._listen())
        await instance._wait_for_ready()
        return instance

    def _log_debug(self, message):
        if self._enable_debug:
            label = f"[{self._debug_label}]" if self._debug_label else ""
            print(f"{label} {message}")

    async def _send(self, data: dict):
        """Sends a JSON message to the WebSocket."""
        message_str = json.dumps(data)
        await self._ws.send(message_str)

    async def _wait_for_ready(self):
        """
        Waits for the initial handshake to complete and the sandbox to be running.
        """
        await self._ready_event.wait()
        if self._error_on_ready:
            raise self._error_on_ready

    async def snapshot_filesystem(self, name: str):
        """
        Triggers the creation of a filesystem snapshot.
        """
        if self._state != "running":
            raise SandboxStateError(f"Sandbox is not in a running state. Current state: {self._state}")

        self._log_debug(f"Requesting filesystem snapshot '{name}'...")
        self._state = "filesystem_snapshotting"
        self._filesystem_snapshot_event.clear()
        self._filesystem_snapshot_error = None

        await self._send({"action": "snapshot_filesystem", "name": name})
        await self._filesystem_snapshot_event.wait()
        if self._filesystem_snapshot_error:
            raise self._filesystem_snapshot_error

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

    def _handle_error_on_ready(self, exc):
        if self._state in ["creating", "attaching"]:
            self._state = "failed"
            self._error_on_ready = exc
            self._ready_event.set()
            self._log_debug(f"Initialization failed: {exc}")

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
                        self._ready_event.set()
                    elif status in [SandboxEvent.SANDBOX_CREATION_ERROR, SandboxEvent.SANDBOX_NOT_FOUND, SandboxEvent.SANDBOX_IN_USE]:
                        error = SandboxCreationError(message.get(MessageKey.MESSAGE, status))
                        self._handle_error_on_ready(error)
                        await self._shutdown()
                        break
                    elif status in [SandboxEvent.SANDBOX_KILLED, SandboxEvent.SANDBOX_KILL_ERROR]:
                        self._killed_event.set()
                        break
                    elif status == SandboxEvent.SANDBOX_FILESYSTEM_SNAPSHOT_CREATED:
                        self._state = "running"
                        self._filesystem_snapshot_event.set()
                    elif status == SandboxEvent.SANDBOX_FILESYSTEM_SNAPSHOT_ERROR:
                        self._filesystem_snapshot_error = SandboxFilesystemSnapshotError(message.get(MessageKey.MESSAGE, status))
                        self._filesystem_snapshot_event.set()
        
        except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError) as e:
            error = SandboxConnectionError(f"Connection closed: {e}")
            self._log_debug(f"Connection closed: {e}")
            self._handle_error_on_ready(error)
            await self._shutdown()
        
        except Exception as e:
            self._log_debug(f"An unexpected error occurred: {e}")
            self._handle_error_on_ready(e)
            await self._shutdown()

    async def _shutdown(self):
        async with self._shutdown_lock:
            if self._state in ["closed", "failed"]:
                return

            self._state = "closed"
            self._log_debug("State changed to closed")

            if self._active_process:
                await self._active_process.kill()
                self._active_process = None

            if self._listen_task and not self._listen_task.done():
                self._stop_event.set()
                # Do not await the listen_task here to avoid deadlock
                # if _shutdown is called from within the listen_task.

            if self._ws and self._ws.state != websockets.protocol.State.CLOSED:
                self._log_debug("Closing WebSocket connection.")
                await self._ws.close()

    async def kill(self, timeout: float = 5.0):
        """
        Terminates the sandbox session.
        """
        if self._state in ["closed", "failed"]:
            return

        self._is_kill_intentionally = True
        self._log_debug("Sending kill command to sandbox...")
        await self._send({"action": "kill_sandbox"})

        try:
            await asyncio.wait_for(self._killed_event.wait(), timeout=timeout)
            self._log_debug("Sandbox killed successfully.")
        except asyncio.TimeoutError:
            self._log_debug("Kill timeout reached. Forcing connection close.")
        finally:
            await self._shutdown()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.kill()