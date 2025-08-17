import asyncio
import json
import websockets
from . import sandbox

# In-memory tracking of sandboxes on this instance.
# In the future, this will be replaced by GCS state.
sandboxes = {}

async def handler(websocket, path):
    """
    Main WebSocket request handler.
    Routes incoming connections based on the path.
    """
    if path == "/create":
        await create_sandbox_handler(websocket)
    elif path.startswith("/attach/"):
        sandbox_id = path.split('/')[-1]
        await attach_sandbox_handler(websocket, sandbox_id)
    else:
        # Fallback for simple HTTP health checks, etc.
        # The websockets library provides a process_request hook for this.
        # For now, we will just close the connection if the path is unknown.
        await websocket.close(1011, "Unknown path")

async def create_sandbox_handler(websocket):
    """
    Handles the creation of a new sandbox.
    """
    await websocket.send(json.dumps({"event": "status_update", "status": "CREATING"}))
    
    # For this first increment, we'll just simulate sandbox creation.
    # We will integrate the actual sandbox.py logic in the next step.
    sandbox_id = "sandbox-" + asyncio.get_running_loop().create_future()._asyncio_future_blocking.__str__()[-4:]
    
    sandboxes[sandbox_id] = {"websocket": websocket, "status": "CREATING"}
    
    await websocket.send(json.dumps({"event": "created", "sandbox_id": sandbox_id}))
    
    sandboxes[sandbox_id]["status"] = "RUNNING"
    await websocket.send(json.dumps({"event": "status_update", "status": "RUNNING"}))

    # Keep the connection open to listen for commands
    try:
        async for message in websocket:
            # In the future, we'll handle commands like stdin, suspend, etc. here.
            await websocket.send(json.dumps({"response": "echo", "data": message}))
    finally:
        print(f"Sandbox {sandbox_id} connection closed.")
        del sandboxes[sandbox_id]


async def attach_sandbox_handler(websocket, sandbox_id):
    """
    Handles attaching to an existing sandbox.
    """
    if sandbox_id in sandboxes:
        # For now, we assume the old connection is dead and just replace it.
        sandboxes[sandbox_id]["websocket"] = websocket
        await websocket.send(json.dumps({"event": "status_update", "status": "RUNNING"}))
        
        try:
            async for message in websocket:
                await websocket.send(json.dumps({"response": "echo", "data": message}))
        finally:
            print(f"Sandbox {sandbox_id} re-attached connection closed.")
            # In a real scenario, we might not want to delete the sandbox on disconnect.
            # For this simple version, we will.
            if sandbox_id in sandboxes:
                del sandboxes[sandbox_id]
    else:
        await websocket.close(1011, f"Sandbox {sandbox_id} not found on this instance.")