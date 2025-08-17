import asyncio
import json
import pytest
from unittest.mock import MagicMock, AsyncMock

from src import handlers

# Mark all tests in this file as asyncio
pytestmark = pytest.mark.asyncio

class MockWebSocket:
    """A mock WebSocket connection for testing handlers."""
    def __init__(self):
        self.sent_messages = []
        self.closed = False
        self.close_code = None
        self.close_reason = ""
        # Simulate receiving messages from the client
        self.client_messages = asyncio.Queue()

    async def send(self, message):
        self.sent_messages.append(json.loads(message))

    async def recv(self):
        # This allows us to control what the client "sends" to the server
        return await self.client_messages.get()

    async def close(self, code=1000, reason=""):
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    # Make the mock websocket an async iterator, like the real one
    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.recv()
        except asyncio.CancelledError:
            raise StopAsyncIteration


async def test_create_sandbox_handler_sends_correct_sequence():
    """
    Tests that the create_sandbox_handler sends the correct sequence of
    status messages upon a successful connection.
    """
    mock_ws = MockWebSocket()

    # We expect the handler to loop forever waiting for messages.
    # We'll run it as a background task and then cancel it after we've
    # received the initial status messages.
    handler_task = asyncio.create_task(handlers.create_sandbox_handler(mock_ws))
    
    # Give the handler a moment to run and send initial messages
    await asyncio.sleep(0.01)

    # Check the initial messages
    assert len(mock_ws.sent_messages) == 3
    assert mock_ws.sent_messages[0]["status"] == "CREATING"
    assert mock_ws.sent_messages[1]["event"] == "created"
    assert "sandbox_id" in mock_ws.sent_messages[1]
    assert mock_ws.sent_messages[2]["status"] == "RUNNING"

    # Check that the sandbox was registered in memory
    sandbox_id = mock_ws.sent_messages[1]["sandbox_id"]
    assert sandbox_id in handlers.sandboxes
    assert handlers.sandboxes[sandbox_id]["status"] == "RUNNING"

    # Clean up the task
    handler_task.cancel()
    try:
        await handler_task
    except asyncio.CancelledError:
        pass # This is expected

    # Cleanup the sandbox from the global dict for other tests
    if sandbox_id in handlers.sandboxes:
        del handlers.sandboxes[sandbox_id]

async def test_attach_to_existing_sandbox():
    """
    Tests that the attach handler correctly connects to a sandbox
    that already exists on the instance.
    """
    mock_ws = MockWebSocket()
    sandbox_id = "test-sandbox-123"
    
    # Manually add a sandbox to the in-memory dict to simulate it running
    handlers.sandboxes[sandbox_id] = {"websocket": None, "status": "RUNNING"}

    # Run the handler as a background task and cancel it after the first message
    handler_task = asyncio.create_task(handlers.attach_sandbox_handler(mock_ws, sandbox_id))
    await asyncio.sleep(0.01)

    assert len(mock_ws.sent_messages) == 1
    assert mock_ws.sent_messages[0]["status"] == "RUNNING"
    assert not mock_ws.closed

    # Clean up
    handler_task.cancel()
    try:
        await handler_task
    except asyncio.CancelledError:
        pass
    
    if sandbox_id in handlers.sandboxes:
        del handlers.sandboxes[sandbox_id]

async def test_attach_to_missing_sandbox():
    """
    Tests that the attach handler correctly closes the connection
    if the requested sandbox does not exist on the instance.
    """
    mock_ws = MockWebSocket()
    sandbox_id = "non-existent-sandbox"

    # The handler should not hang, it should close and exit
    await handlers.attach_sandbox_handler(mock_ws, sandbox_id)

    assert len(mock_ws.sent_messages) == 0
    assert mock_ws.closed
    assert mock_ws.close_code == 1011
    assert "not found" in mock_ws.close_reason