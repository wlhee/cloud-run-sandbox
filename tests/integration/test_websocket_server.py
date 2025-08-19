import asyncio
import pytest
import threading
import websockets
import json
from src import server, handlers

# Mark all tests in this file as asyncio
pytestmark = pytest.mark.asyncio

@pytest.fixture(scope="module")
def event_loop():
    """Create an instance of the default event loop for each test module."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="module")
def running_server(event_loop):
    """
    Pytest fixture to run the WebSocket server in a background thread.
    """
    # Reset the sandboxes dict for a clean slate
    handlers.sandboxes = {}
    
    stop_server = asyncio.Future(loop=event_loop)

    def run_server():
        asyncio.set_event_loop(event_loop)
        async def server_task():
            async with websockets.serve(handlers.handler, "localhost", server.PORT):
                await stop_server
        event_loop.run_until_complete(server_task())

    server_thread = threading.Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Give the server a moment to start up
    asyncio.run(asyncio.sleep(0.1))
    
    yield
    
    # Teardown
    event_loop.call_soon_threadsafe(stop_server.set_result, True)
    server_thread.join(timeout=1)


async def test_create_and_attach_workflow(running_server):
    """
    Tests the full workflow of creating a sandbox, receiving its ID,
    and then re-attaching to it.
    """
    uri_create = f"ws://localhost:{server.PORT}/create"
    sandbox_id = None

    # 1. Test the /create endpoint
    async with websockets.connect(uri_create) as websocket:
        message = await websocket.recv()
        data = json.loads(message)
        assert data["status"] == "CREATING"

        message = await websocket.recv()
        data = json.loads(message)
        assert data["event"] == "created"
        sandbox_id = data.get("sandbox_id")
        assert sandbox_id is not None

        message = await websocket.recv()
        data = json.loads(message)
        assert data["status"] == "RUNNING"

        await websocket.send("hello")
        response = await websocket.recv()
        response_data = json.loads(response)
        assert response_data["response"] == "echo"
        assert response_data["data"] == "hello"

    assert sandbox_id is not None
    
    uri_attach = f"ws://localhost:{server.PORT}/attach/{sandbox_id}"

    # 2. Test the /attach endpoint
    async with websockets.connect(uri_attach) as websocket:
        message = await websocket.recv()
        data = json.loads(message)
        assert data["status"] == "RUNNING"

        await websocket.send("world")
        response = await websocket.recv()
        response_data = json.loads(response)
        assert response_data["response"] == "echo"
        assert response_data["data"] == "world"

async def test_attach_to_non_existent_sandbox(running_server):
    """
    Tests that the server sends a NOT_FOUND message and closes the
    connection when a client tries to attach to a non-existent sandbox.
    """
    uri = f"ws://localhost:{server.PORT}/attach/non-existent-id"
    
    async with websockets.connect(uri) as websocket:
        message = await websocket.recv()
        data = json.loads(message)
        assert data["status"] == "NOT_FOUND"

        # After sending NOT_FOUND, the server should close the connection.
        # Trying to receive again should raise a ConnectionClosed error.
        with pytest.raises(websockets.exceptions.ConnectionClosed) as excinfo:
            await websocket.recv()
        
        assert excinfo.value.code == 1011
        assert "not found" in excinfo.value.reason
