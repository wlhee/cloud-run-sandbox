from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException
from src.sandbox.manager import manager as sandbox_manager
from src.sandbox.interface import SandboxCreationError, SandboxExecutionError, SandboxStreamClosed
from src.sandbox.types import SandboxStateEvent, CodeLanguage
import asyncio
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

class WebsocketHandler:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.sandbox = None

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
            await self.send_status(SandboxStateEvent.SANDBOX_CREATION_ERROR)
            await self.websocket.close(code=4000, reason=str(e))
        except WebSocketException as e:
            logger.error(f"WebSocket error during sandbox creation: {e}")
            await self.websocket.close(code=e.code, reason=str(e))
        except WebSocketDisconnect:
            logger.info(f"Client disconnected before sandbox creation completed.")
        finally:
            if self.sandbox:
                # The idle manager will handle the final deletion.
                logger.info(f"Finished handling websocket for sandbox {self.sandbox.sandbox_id}")

    async def execution_loop(self):
        """
        Continuously waits for code execution requests and streams the results.
        """
        while True:
            try:
                message = await self.websocket.receive_json()
                language = CodeLanguage(message['language'])
                code = message['code']

                await self.sandbox.execute(language, code=code)
                await self.stream_output()

            except (KeyError, ValueError):
                supported_languages = ", ".join([lang.value for lang in CodeLanguage])
                await self.handle_error(
                    SandboxExecutionError(
                        "Invalid message format. 'language' and 'code' fields are required. "
                        f"Supported languages are: {supported_languages}"
                    ),
                    close_connection=False
                )
            except SandboxExecutionError as e:
                # For execution errors, send the error but keep the connection open
                await self.handle_error(e, close_connection=False)
            except (WebSocketException, WebSocketDisconnect):
                # If the client disconnects, break the loop
                raise

    async def stream_output(self):
        try:
            async for event in self.sandbox.connect():
                await self.websocket.send_json({
                    "event": event["type"].value,
                    "data": event["data"]
                })
        except SandboxStreamClosed:
            logger.info(f"Stream closed for sandbox {self.sandbox.sandbox_id}")

    async def send_status(self, status: SandboxStateEvent):
        await self.websocket.send_json({"event": "status_update", "status": status.value})

    async def handle_error(self, e: Exception, close_connection: bool):
        if isinstance(e, SandboxExecutionError):
            error_status = SandboxStateEvent.SANDBOX_EXECUTION_ERROR
        elif isinstance(e, SandboxCreationError):
            error_status = SandboxStateEvent.SANDBOX_CREATION_ERROR
        else:
            # Fallback for other unexpected errors
            error_status = SandboxStateEvent.SANDBOX_EXECUTION_ERROR

        await self.send_status(error_status)
        await self.websocket.send_json({"event": "error", "message": str(e)})
        
        if close_connection:
            await self.websocket.close(code=1011)

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
