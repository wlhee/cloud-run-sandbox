
import asyncio
import websockets
from typing import Callable, Any, Dict, Optional

class Connection:
    """
    Manages the lifecycle of a WebSocket connection, handling the raw
    communication and delegating events to the consumer via callbacks.
    """
    def __init__(
        self,
        url: str,
        on_message: Callable[[str], Any],
        on_error: Callable[[Exception], Any],
        on_close: Callable[[int, str], Any],
        ws_options: Optional[Dict[str, Any]] = None,
        debug: bool = False,
        debug_label: str = '',
    ):
        self.url = url
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.ws_options = ws_options or {}
        self._debug_enabled = debug
        self._debug_label = debug_label
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._listen_task: Optional[asyncio.Task] = None

    def _log_debug(self, message, *args):
        if self._debug_enabled:
            print(f"[{self._debug_label}] [DEBUG] {message}", *args)

    async def connect(self):
        """
        Establishes the WebSocket connection and starts the listener task.
        """
        self._log_debug(f"Connecting to {self.url}")
        try:
            # The `extra_headers` kwarg is used by websockets for custom headers.
            # We will use this later for cookies.
            self.ws = await websockets.connect(self.url, **self.ws_options)
            self._log_debug("Connection established.")
            self._listen_task = asyncio.create_task(self._listen())
        except Exception as e:
            self._log_debug(f"Connection failed: {e}")
            self.on_error(e)
            raise

    async def _listen(self):
        """
        Listens for incoming messages and handles connection state changes.
        """
        try:
            while True:
                message = await self.ws.recv()
                self.on_message(message)
        except websockets.exceptions.ConnectionClosed as e:
            self._log_debug(f"Connection closed: {e.code} {e.reason}")
            self.on_close(e.code, e.reason)
        except Exception as e:
            self._log_debug(f"An error occurred in listener: {e}")
            self.on_error(e)
            # Ensure close is called on unexpected errors
            if self.ws and self.ws.state != websockets.protocol.State.CLOSED:
                 await self.ws.close(1011, "Unexpected error")
            self.on_close(1011, "Unexpected error")

    async def send(self, data: str):
        """
        Sends a message over the WebSocket connection.
        """
        if self.ws and self.ws.state != websockets.protocol.State.CLOSED: 
            await self.ws.send(data)
        else:
            raise ConnectionError("WebSocket is not connected.")

    async def close(self, code: int = 1000, reason: str = ""):
        """
        Closes the WebSocket connection and cancels the listener task.
        """
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
        if self.ws and self.ws.state != websockets.protocol.State.CLOSED:
            self._log_debug("Closing WebSocket connection.")
            await self.ws.close(code, reason)
