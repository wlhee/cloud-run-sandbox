import asyncio
import json
import weakref
import websockets

from .types import MessageKey, EventType, SandboxEvent
from .exceptions import SandboxConnectionError, SandboxCreationError
from .process import SandboxProcess

class Sandbox:
    """
    Represents a connection to a Cloud Run Sandbox, used to execute commands.
    """
    def __init__(self, websocket):
        self._ws = websocket
        self._sandbox_id = None
        self._active_process = None
        self._created_event = asyncio.Event()
        self._creation_error = None
        self._listen_task = asyncio.create_task(self._listen())
        self._state = "creating"

    @property
    def sandbox_id(self):
        """The unique ID of the sandbox."""
        return self._sandbox_id

    @classmethod
    async def create(cls, url: str, idle_timeout: int = 60, ssl=None):
        """
        Creates a new sandbox session.
        """
        try:
            # Use __await__ to make it compatible with the AsyncMock from tests
            sanitized_url = url.rstrip('/')
            websocket = await websockets.connect(f"{sanitized_url}/create", ssl=ssl)
        except websockets.exceptions.InvalidURI as e:
            raise SandboxConnectionError(f"Invalid WebSocket URI: {e}")
        except ConnectionRefusedError:
            raise SandboxConnectionError(f"Connection refused for WebSocket URI: {url}")

        await websocket.send(json.dumps({"idle_timeout": idle_timeout}))
        
        sandbox = cls(websocket)
        await sandbox._wait_for_creation()
        return sandbox

    async def _wait_for_creation(self):
        """
        Waits for the initial handshake to complete and the sandbox to be running.
        """
        await self._created_event.wait()
        if self._creation_error:
            await self._listen_task
            raise self._creation_error


    async def exec(self, code: str, language: str) -> SandboxProcess:
        """
        Creates and starts a new process in the sandbox for code execution.
        """
        if self._active_process:
            raise RuntimeError("Another process is already running in this sandbox.")
        if self._state != "running":
            raise RuntimeError(f"Sandbox is not in a running state. Current state: {self._state}")

        process = SandboxProcess(self._ws, on_done=self._clear_active_process)
        self._active_process = process
        
        await process.exec(code, language)
        return process

    def _clear_active_process(self):
        self._active_process = None

    async def _listen(self):
        """
        Listens for all incoming WebSocket messages and dispatches them.
        """
        try:
            while True:
                message_str = await self._ws.recv()
                message = json.loads(message_str)
                event = message.get(MessageKey.EVENT)

                # Process-specific events are always forwarded
                if (event in [EventType.STDOUT, EventType.STDERR] or
                    (event == EventType.STATUS_UPDATE and 
                     message.get(MessageKey.STATUS, "").startswith("SANDBOX_EXECUTION_"))):
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
                        if self._state == "creating":
                            self._state = "failed"
                            self._creation_error = SandboxCreationError(message.get(MessageKey.MESSAGE, status))
                            self._created_event.set()
        
        except websockets.exceptions.ConnectionClosed:
            if self._state == "creating":
                self._state = "failed"
                self._creation_error = SandboxConnectionError("Connection closed during creation")
                self._created_event.set()
            else:
                self._state = "closed"
            
            if self._active_process:
                self._active_process.terminate()
                self._active_process = None
        
        except Exception as e:
            if self._state == "creating":
                self._state = "failed"
                self._creation_error = e
                self._created_event.set()
            
            if self._active_process:
                self._active_process.terminate()
                self._active_process = None


    async def terminate(self):
        """
        Terminates the sandbox session.
        """
        if self._active_process:
            self._active_process.terminate()
            self._active_process = None

        if self._ws.state != websockets.protocol.State.CLOSED:
            await self._ws.close()
        
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.terminate()