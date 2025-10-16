from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException
from src.sandbox.manager import manager as sandbox_manager
from src.sandbox.interface import SandboxCreationError, SandboxExecutionError, SandboxExecutionInProgressError, SandboxStreamClosed, SandboxOperationError, SandboxCheckpointError, SandboxRestoreError, SandboxSnapshotFilesystemError, SandboxError
from src.sandbox.types import SandboxStateEvent, CodeLanguage
import asyncio
import logging
from functools import partial

logger = logging.getLogger(__name__)
router = APIRouter()

class WebsocketHandler:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.sandbox = None
        self.active_tasks = set()

    async def _websocket_lifecycle(self, setup_coro):
        """
        Manages the entire lifecycle of a websocket connection, ensuring
        proper setup and teardown.
        """
        await self.websocket.accept()
        try:
            # Run the specific setup logic (create or attach)
            success = await setup_coro()
            if success:
                # If setup was successful, start the main execution loop
                await self.execution_loop()
        except (WebSocketDisconnect, WebSocketException) as e:
            # This will catch disconnects that happen outside the main execution loop
            # (e.g., during sandbox creation).
            logger.info(f"WebSocket connection closed: {e}")
        finally:
            # Ensure all background tasks are cancelled on handler exit.
            for task in self.active_tasks:
                task.cancel()
            if self.sandbox:
                self.sandbox.is_attached = False
                logger.info(f"Finished handling websocket for sandbox {self.sandbox.sandbox_id}")

    async def _setup_create(self):
        """Sets up the handler for a new sandbox."""
        try:
            # 1. Wait for the initial configuration message
            init_message = await self.websocket.receive_json()
            idle_timeout = init_message.get("idle_timeout", 300)
            enable_checkpoint = init_message.get("enable_checkpoint", False)
            filesystem_snapshot_name = init_message.get("filesystem_snapshot_name")

            await self.send_status(SandboxStateEvent.SANDBOX_CREATING)

            if enable_checkpoint and not sandbox_manager.is_sandbox_checkpointing_enabled:
                raise SandboxCreationError("Checkpointing is not enabled on the server.")
            
            if filesystem_snapshot_name and not sandbox_manager.is_filesystem_snapshotting_enabled:
                raise SandboxCreationError("Filesystem snapshot is not enabled on the server.")

            self.sandbox = await sandbox_manager.create_sandbox(
                idle_timeout=idle_timeout,
                enable_checkpoint=enable_checkpoint,
                filesystem_snapshot_name=filesystem_snapshot_name,
            )
            self.sandbox.is_attached = True
            await self.websocket.send_json({"event": "sandbox_id", "sandbox_id": self.sandbox.sandbox_id})
            
            # 3. Signal that the sandbox is ready
            await self.send_status(SandboxStateEvent.SANDBOX_RUNNING)
            return True  # Indicates success
        except SandboxCreationError as e:
            logger.error(f"Sandbox creation failed: {e}")
            await self.handle_error(e, close_connection=True)
            return False  # Indicates failure

    async def _setup_attach(self, sandbox_id: str):
        """Sets up the handler for an existing sandbox."""
        try:
            sandbox = sandbox_manager.get_sandbox(sandbox_id)
            if not sandbox and sandbox_manager.is_sandbox_checkpointing_enabled:
                await self.send_status(SandboxStateEvent.SANDBOX_RESTORING)
                sandbox = await sandbox_manager.restore_sandbox(sandbox_id)

            if not sandbox:
                await self.send_status(SandboxStateEvent.SANDBOX_NOT_FOUND)
                await self.websocket.close(code=1011)
                return False  # Indicates failure
            
            if sandbox.is_attached:
                await self.send_status(SandboxStateEvent.SANDBOX_IN_USE)
                await self.websocket.close(code=1011)
                return False

            self.sandbox = sandbox
            self.sandbox.is_attached = True
            await self.send_status(SandboxStateEvent.SANDBOX_RUNNING)
            return True  # Indicates success
        except Exception as e:
            e = SandboxRestoreError(f"Failed to restore sandbox {sandbox_id}: {e}")
            await self.handle_error(e, close_connection=True)
            return False

    async def handle_create(self):
        """Public entrypoint to handle a 'create' websocket connection."""
        await self._websocket_lifecycle(self._setup_create)

    async def handle_attach(self, sandbox_id: str):
        """Public entrypoint to handle an 'attach' websocket connection."""
        setup_coro = partial(self._setup_attach, sandbox_id=sandbox_id)
        await self._websocket_lifecycle(setup_coro)

    async def execution_loop(self):
        """
        Continuously waits for code execution requests and launches them in
        the background.
        """
        try:
            while True:
                message = await self.websocket.receive_json()
                task = None
                if message.get("action") == "checkpoint":
                    task = asyncio.create_task(self.handle_checkpoint())
                elif message.get("action") == "snapshot_filesystem":
                    task = asyncio.create_task(self.handle_snapshot_filesystem(message))
                elif message.get("event") == "stdin":
                    task = asyncio.create_task(self.handle_stdin(message))
                else:
                    task = asyncio.create_task(self.run_and_stream(message))
                
                if task:
                    self.active_tasks.add(task)
                    task.add_done_callback(self.active_tasks.discard)
        except (WebSocketDisconnect, WebSocketException):
            logger.info(f"Client disconnected from sandbox {self.sandbox.sandbox_id if self.sandbox else 'unknown'}")

    async def handle_checkpoint(self):
        """Handles a checkpoint request from the client."""
        print(f"WEBSOCKET ({self.sandbox.sandbox_id}): Received checkpoint action from client.")
        try:
            await self.send_status(SandboxStateEvent.SANDBOX_CHECKPOINTING)
            await sandbox_manager.checkpoint_sandbox(self.sandbox.sandbox_id)
            await self.send_status(SandboxStateEvent.SANDBOX_CHECKPOINTED)
            await self.websocket.close(code=1000)
        except SandboxExecutionInProgressError as e:
            print(f"WEBSOCKET ({self.sandbox.sandbox_id}): Caught SandboxExecutionInProgressError.")
            await self.handle_error(e, close_connection=False)
        except Exception as e:
            e = SandboxCheckpointError(f"Failed to checkpoint sandbox {self.sandbox.sandbox_id}: {e}")
            await self.handle_error(e, close_connection=True)

    async def handle_snapshot_filesystem(self, message: dict):
        """Handles a snapshot filesystem request from the client."""
        try:
            await self.send_status(SandboxStateEvent.SANDBOX_FILESYSTEM_SNAPSHOT_CREATING)
            if not sandbox_manager.is_filesystem_snapshotting_enabled:
                logger.error(f"Filesystem snapshot rejected for sandbox {self.sandbox.sandbox_id}: feature is not enabled on the server.")
                raise SandboxOperationError("Filesystem snapshot is not enabled on the server.")

            snapshot_name = message['name']
            await sandbox_manager.snapshot_filesystem(self.sandbox.sandbox_id, snapshot_name)
            await self.send_status(SandboxStateEvent.SANDBOX_FILESYSTEM_SNAPSHOT_CREATED)
        except (SandboxOperationError, SandboxSnapshotFilesystemError) as e:
            e = SandboxSnapshotFilesystemError(f"Failed to snapshot filesystem for sandbox {self.sandbox.sandbox_id}: {e}")
            await self.handle_error(e, close_connection=False)
        except Exception as e:
            e = SandboxError(f"Failed to snapshot filesystem for sandbox {self.sandbox.sandbox_id}: {e}")
            await self.handle_error(e, close_connection=True)

    async def handle_stdin(self, message: dict):
        """Handles a stdin message from the client."""
        try:
            data = message['data']
            await self.sandbox.write_stdin(data)
        except (KeyError, ValueError) as e:
            await self.handle_error(e, close_connection=False, message=message)
        except Exception as e:
            logger.error(f"Unexpected error during stdin write: {e}")
            await self.handle_error(e, close_connection=False, message=message)

    async def run_and_stream(self, message: dict):
        """
        Handles a single code execution request, including streaming the output.
        """
        try:
            language = CodeLanguage(message['language'])
            code = message['code']

            await self.sandbox.execute(language, code=code)
            
            async for event in self.sandbox.stream_outputs():
                if event["type"] == "status_update":
                    await self.send_status(SandboxStateEvent(event["status"]))
                else:
                    await self.websocket.send_json({
                        "event": event["type"].value,
                        "data": event["data"]
                    })

        except SandboxStreamClosed:
            # This is the expected end of a stream, not an error.
            pass
        except (SandboxOperationError, KeyError, ValueError) as e:
            await self.handle_error(e, close_connection=False, message=message)
        except Exception as e:
            logger.error(f"Unexpected error during execution: {e}")
            await self.handle_error(e, close_connection=True, message=message)

    async def send_status(self, status: SandboxStateEvent):
        await self.websocket.send_json({"event": "status_update", "status": status.value})

    async def handle_error(self, e: Exception, close_connection: bool, message: dict = None):
        error_status = SandboxStateEvent.SANDBOX_ERROR

        if isinstance(e, SandboxRestoreError):
            error_status = SandboxStateEvent.SANDBOX_RESTORE_ERROR
        elif isinstance(e, SandboxExecutionInProgressError):
            error_status = SandboxStateEvent.SANDBOX_EXECUTION_IN_PROGRESS_ERROR
        elif isinstance(e, SandboxCheckpointError):
            error_status = SandboxStateEvent.SANDBOX_CHECKPOINT_ERROR
        elif isinstance(e, SandboxSnapshotFilesystemError):
            error_status = SandboxStateEvent.SANDBOX_FILESYSTEM_SNAPSHOT_ERROR
        elif isinstance(e, SandboxOperationError):
            error_status = SandboxStateEvent.SANDBOX_EXECUTION_ERROR
        elif isinstance(e, (KeyError, ValueError)):
            if message and message.get("event") == "stdin":
                e = SandboxExecutionError("Invalid stdin message format. 'data' field is required.")
                error_status = SandboxStateEvent.SANDBOX_STDIN_ERROR
            else:
                supported_languages = ", ".join([lang.value for lang in CodeLanguage])
                e = SandboxExecutionError(
                    "Invalid message format. 'language' and 'code' fields are required. "
                    f"Supported languages are: {supported_languages}"
                )
                error_status = SandboxStateEvent.SANDBOX_EXECUTION_ERROR
        elif isinstance(e, SandboxCreationError):
            error_status = SandboxStateEvent.SANDBOX_CREATION_ERROR
        else:
            error_status = SandboxStateEvent.SANDBOX_ERROR

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
    handler = WebsocketHandler(websocket)
    await handler.handle_attach(sandbox_id)
