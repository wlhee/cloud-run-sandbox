from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.sandbox.manager import manager as sandbox_manager
from src.sandbox.interface import SandboxCreationError, SandboxStartError
from src.sandbox.events import SandboxStateEvent
import asyncio

router = APIRouter()

@router.websocket("/create")
async def create(websocket: WebSocket):
    """
    Creates a new sandbox and starts it.
    """
    await websocket.accept()
    await websocket.send_json({"event": "status_update", "status": SandboxStateEvent.SANDBOX_CREATING.value})
    
    sandbox = None
    try:
        sandbox = await sandbox_manager.create_sandbox()
        await websocket.send_json({"event": "sandbox_id", "sandbox_id": sandbox.sandbox_id})
        
        await sandbox.start(code="") # In future, code will come from client
        await websocket.send_json({"event": "status_update", "status": SandboxStateEvent.SANDBOX_RUNNING.value})
        
        async for event in sandbox.connect():
            await websocket.send_json({
                "event": event["type"].value,
                "data": event["data"]
            })

    except SandboxCreationError as e:
        await websocket.send_json({"event": "status_update", "status": SandboxStateEvent.SANDBOX_CREATION_ERROR.value})
        await websocket.send_json({"event": "error", "message": str(e)})
        await websocket.close(code=1011)
    except SandboxStartError as e:
        await websocket.send_json({"event": "status_update", "status": SandboxStateEvent.SANDBOX_START_ERROR.value})
        await websocket.send_json({"event": "error", "message": str(e)})
        await websocket.close(code=1011)
    except WebSocketDisconnect:
        print(f"Client disconnected.")
    finally:
        if sandbox:
            await sandbox_manager.delete_sandbox(sandbox.sandbox_id)

@router.websocket("/attach/{sandbox_id}")
async def attach(websocket: WebSocket, sandbox_id: str):
    """
    Attaches to an existing sandbox.
    """
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
        except WebSocketDisconnect:
            print(f"Attached client for {sandbox.sandbox_id} disconnected.")
        finally:
            await sandbox_manager.delete_sandbox(sandbox.sandbox_id)
    else:
        await websocket.send_json({"event": "status_update", "status": SandboxStateEvent.SANDBOX_NOT_FOUND.value})
        await websocket.close(code=1011)