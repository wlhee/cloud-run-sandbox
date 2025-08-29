from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException
from src.sandbox.manager import manager as sandbox_manager
from src.sandbox.interface import SandboxCreationError, SandboxExecutionError, SandboxStreamClosed, SandboxOperationError
from src.sandbox.types import SandboxStateEvent, CodeLanguage
import asyncio
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

class WebsocketHandler:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.sandbox = None
        self.active_tasks = set()

    async def handle_create(self):
        await self.websocket.accept()
        
        try:
            # 1. Wait for the initial configuration message
            init_message = await self.websocket.receive_json()
            idle_timeout = init_message.get("idle_timeout", 300)

            # 2. Create the sandbox
            await self.send_status(SandboxStateEvent.SANDBOX_CREATING)
            self.sandbox = await sandbox_manager.create_sandbox(idle_timeout=idle_timeout)
            await self.websocket.send_json({"event": "sandbox_id", "sandbox_id": self.sandbox.sandbox_id})
            
            # 3. Signal that the sandbox is ready and enter the execution loop
            await self.send_status(SandboxStateEvent.SANDBOX_RUNNING)
            await self.execution_loop()

        except SandboxCreationError as e:
            logger.error(f"Sandbox creation failed: {e}")
            await self.handle_error(e, close_connection=True)
        except (WebSocketDisconnect, WebSocketException) as e:
            # This will catch disconnects that happen outside the main execution loop
            # (e.g., during sandbox creation).
            logger.info(f"WebSocket connection closed: {e}")
        finally:
            # Ensure all background tasks are cancelled on handler exit.
            for task in self.active_tasks:
                task.cancel()
            if self.sandbox:
                logger.info(f"Finished handling websocket for sandbox {self.sandbox.sandbox_id}")

    async def execution_loop(self):
        """
        Continuously waits for code execution requests and launches them in
        the background.
        """
        try:
            while True:
                message = await self.websocket.receive_json()
                task = asyncio.create_task(self.run_and_stream(message))
                self.active_tasks.add(task)
                task.add_done_callback(self.active_tasks.discard)
        except (WebSocketDisconnect, WebSocketException):
            logger.info(f"Client disconnected from sandbox {self.sandbox.sandbox_id if self.sandbox else 'unknown'}")

    async def run_and_stream(self, message: dict):
        """
        Handles a single code execution request, including streaming the output.
        """
        try:
            language = CodeLanguage(message['language'])
            code = message['code']

            await self.sandbox.execute(language, code=code)
            
            async for event in self.sandbox.connect():
                await self.websocket.send_json({
                    "event": event["type"].value,
                    "data": event["data"]
                })

        except SandboxStreamClosed:
            # This is the expected end of a stream, not an error.
            pass
        except (SandboxOperationError, KeyError, ValueError) as e:
            await self.handle_error(e, close_connection=False)
        except Exception as e:
            logger.error(f"Unexpected error during execution: {e}")
            await self.handle_error(e, close_connection=False)

    async def send_status(self, status: SandboxStateEvent):
        await self.websocket.send_json({"event": "status_update", "status": status.value})

    async def handle_error(self, e: Exception, close_connection: bool):
        if isinstance(e, SandboxOperationError):
            error_status = SandboxStateEvent.SANDBOX_EXECUTION_ERROR
        elif isinstance(e, (KeyError, ValueError)):
            supported_languages = ", ".join([lang.value for lang in CodeLanguage])
            e = SandboxExecutionError(
                "Invalid message format. 'language' and 'code' fields are required. "
                f"Supported languages are: {supported_languages}"
            )
            error_status = SandboxStateEvent.SANDBOX_EXECUTION_ERROR
        elif isinstance(e, SandboxCreationError):
            error_status = SandboxStateEvent.SANDBOX_CREATION_ERROR
        else:
            error_status = SandboxStateEvent.SANDBOX_EXECUTION_ERROR

        await self.send_status(error_status)
        await self.websocket.send_json({"event": "error", "message": str(e)})

        if close_connection:
            await self.websocket.close(code=4000)

@router.websocket("/create")
async def create(websocket: WebSocket):
    handler = WebsocketHandler(websocket)
    await handler.handle_create()

@router.websocket("/attach/{sandbox_id}")
async def attach(websocket: WebSocket, sandbox_id: str):
    """
    Attaches to an existing sandbox.
    """
    # This endpoint remains unchanged for now.
    await websocket.accept()
    sandbox = sandbox_manager.get_sandbox(sandbox_id)
    
    if sandbox:
        try:
            await websocket.send_json({"event": "status_update", "status": SandboxStateEvent.SANDBOX_RUNNING.value})
            async for event in sandbox.connect():
                await websocket.send_json({
                    "event": event["type"].value,
                    "data": event["data"]
                })
        except (WebSocketDisconnect, SandboxStreamClosed):
            logger.info(f"Attached client for {sandbox.sandbox_id} disconnected.")
    else:
        await websocket.send_json({"event": "status_update", "status": SandboxStateEvent.SANDBOX_NOT_FOUND.value})
        await websocket.close(code=1011)
