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
        self._processes = weakref.WeakSet()
        self._created_event = asyncio.Event()
        self._creation_error = None
        self._listen_task = asyncio.create_task(self._listen())

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
            websocket = await websockets.connect(f"{url}/create", ssl=ssl)
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
        # Note: The server currently only supports one execution at a time.
        process = SandboxProcess(self._ws)
        self._processes.add(process)
        await process.exec(code, language)
        return process

    async def _listen(self):
        """
        Listens for connection-level events.
        """
        try:
            # The `async for` is not compatible with the `recv` mock pattern.
            # This `while` loop makes it directly compatible.
            while True:
                message_str = await self._ws.recv()
                message = json.loads(message_str)
                event = message.get(MessageKey.EVENT)

                if event == EventType.SANDBOX_ID:
                    self._sandbox_id = message.get(MessageKey.SANDBOX_ID)
                    continue

                if event == EventType.STATUS_UPDATE:
                    status = message.get(MessageKey.STATUS)
                    if status == SandboxEvent.SANDBOX_RUNNING and self._sandbox_id:
                        self._created_event.set()
                        # This listener's job is done for creation, but it needs to
                        # stay alive for the process communication.
                        # We will rely on the process listener to take over.
                        # For now, we just stop processing sandbox-level events.
                        return

                    if status == SandboxEvent.SANDBOX_CREATION_ERROR:
                        self._creation_error = SandboxCreationError(message.get(MessageKey.MESSAGE))
                        self._created_event.set()
                        # The listener's job is done, break the loop.
                        break
        
        except websockets.exceptions.ConnectionClosed:
            pass # Expected on terminate
        
        finally:
            # If the connection is lost before creation is confirmed, mark it as an error.
            if not self._created_event.is_set():
                self._creation_error = SandboxConnectionError("Connection lost before sandbox was created")
                self._created_event.set()


    async def terminate(self):
        """
        Terminates the sandbox session, ensuring all child processes are stopped.
        """
        # Terminate all running processes concurrently
        await asyncio.gather(*(process.terminate() for process in self._processes))

        if self._ws.state != websockets.protocol.State.CLOSED:
            await self._ws.close()
        
        self._listen_task.cancel()
        try:
            await self._listen_task
        except asyncio.CancelledError:
            pass