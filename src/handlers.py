import asyncio
import json
import uuid
import websockets
from . import sandbox

# In-memory tracking of sandboxes on this instance.
sandboxes = {}

async def handler(websocket):
    """
    Main WebSocket request handler.
    Routes incoming connections based on the path.
    """
    path = websocket.request.path
    if path == "/create":
        await create_sandbox_handler(websocket)
    elif path.startswith("/attach/"):
        sandbox_id = path.split('/')[-1]
        await attach_sandbox_handler(websocket, sandbox_id)
    # For unknown paths, the connection is accepted and immediately closed.

async def create_sandbox_handler(websocket):
    """
    Handles the creation of a new sandbox.
    """
    await websocket.send(json.dumps({"event": "status_update", "status": "CREATING"}))
    
    sandbox_id = "sandbox-" + str(uuid.uuid4())[:4]
    sandboxes[sandbox_id] = {"websocket": websocket, "status": "CREATING"}
    print(f"*** CREATED sandbox {sandbox_id}. Current sandboxes: {list(sandboxes.keys())}")
    
    await websocket.send(json.dumps({"event": "created", "sandbox_id": sandbox_id}))
    
    sandboxes[sandbox_id]["status"] = "RUNNING"
    await websocket.send(json.dumps({"event": "status_update", "status": "RUNNING"}))

    try:
        async for message in websocket:
            await websocket.send(json.dumps({"response": "echo", "data": message}))
    finally:
        # The sandbox should continue to exist even if the creator disconnects.
        print(f"*** Initial client for {sandbox_id} disconnected. Current sandboxes: {list(sandboxes.keys())}")

async def attach_sandbox_handler(websocket, sandbox_id):
    """
    Handles attaching to an existing sandbox.
    """
    print(f"*** ATTACH request for {sandbox_id}. Current sandboxes: {list(sandboxes.keys())}")
    if sandbox_id in sandboxes:
        sandboxes[sandbox_id]["websocket"] = websocket
        await websocket.send(json.dumps({"event": "status_update", "status": "RUNNING"}))
        
        try:
            async for message in websocket:
                await websocket.send(json.dumps({"response": "echo", "data": message}))
        finally:
            print(f"Sandbox {sandbox_id} re-attached connection closed.")
            if sandbox_id in sandboxes:
                del sandboxes[sandbox_id]
    else:
        # If sandbox is not found, inform the client and close gracefully.
        print(f"*** Sandbox {sandbox_id} NOT FOUND. Sending NOT_FOUND and closing.")
        await websocket.send(json.dumps({"event": "status_update", "status": "NOT_FOUND"}))
        await websocket.close(1011, f"Sandbox {sandbox_id} not found")