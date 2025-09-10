import asyncio
import json
import pytest
import websockets
from unittest.mock import AsyncMock, patch

from codesandbox.sandbox import Sandbox
from codesandbox.exceptions import SandboxCreationError
from codesandbox.types import MessageKey, EventType, SandboxEvent

@pytest.mark.asyncio
@patch('codesandbox.sandbox.websockets.connect', new_callable=AsyncMock)
async def test_sandbox_create_success(mock_connect):
    """
    Tests that a sandbox is created successfully without race conditions.
    """
    # Arrange
    mock_ws = AsyncMock()
    mock_ws.closed = False
    mock_connect.return_value = mock_ws

    messages = [
        json.dumps({MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"}),
        json.dumps({MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING}),
    ]
    # The _listen loop will terminate when this is raised.
    side_effects = messages + [websockets.exceptions.ConnectionClosed(None, None)]
    
    # Use a queue to feed messages to the mock recv
    q = asyncio.Queue()
    for item in side_effects:
        await q.put(item)

    async def recv_side_effect():
        item = await q.get()
        if isinstance(item, Exception):
            mock_ws.closed = True
            raise item
        return item
    mock_ws.recv.side_effect = recv_side_effect

    # Act
    # This will start the _listen task and correctly wait for the _created_event
    sandbox = await Sandbox.create("ws://test")
    
    # Assert
    assert sandbox.sandbox_id == "test_id"
    mock_ws.send.assert_called_once()
    
    # Clean up the background task
    await sandbox.terminate()

@pytest.mark.asyncio
@patch('codesandbox.sandbox.websockets.connect', new_callable=AsyncMock)
async def test_sandbox_create_failure(mock_connect):
    """
    Tests that sandbox creation raises an exception on error.
    """
    # Arrange
    mock_ws = AsyncMock()
    mock_ws.closed = False
    mock_connect.return_value = mock_ws

    messages = [
        json.dumps({
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_CREATION_ERROR,
            MessageKey.MESSAGE: "Failed to create sandbox"
        }),
    ]
    side_effects = messages + [websockets.exceptions.ConnectionClosed(None, None)]

    q = asyncio.Queue()
    for item in side_effects:
        await q.put(item)

    async def recv_side_effect():
        item = await q.get()
        if isinstance(item, Exception):
            mock_ws.closed = True
            raise item
        return item
    mock_ws.recv.side_effect = recv_side_effect
    
    # Act & Assert
    with pytest.raises(SandboxCreationError, match="Failed to create sandbox"):
        await Sandbox.create("ws://test")

@pytest.mark.asyncio
@patch('codesandbox.sandbox.websockets.connect', new_callable=AsyncMock)
@patch('codesandbox.sandbox.SandboxProcess')
async def test_sandbox_terminate_kills_processes(MockSandboxProcess, mock_connect):
    """
    Tests that terminating a sandbox also terminates its active child processes.
    """
    # Arrange
    mock_ws = AsyncMock()
    mock_ws.closed = False
    mock_connect.return_value = mock_ws

    messages = [
        json.dumps({MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"}),
        json.dumps({MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING}),
    ]
    side_effects = messages + [websockets.exceptions.ConnectionClosed(None, None)]
    
    q = asyncio.Queue()
    for item in side_effects:
        await q.put(item)
    mock_ws.recv.side_effect = q.get

    # Create mock processes
    process1 = AsyncMock()
    process2 = AsyncMock()
    MockSandboxProcess.side_effect = [process1, process2]

    sandbox = await Sandbox.create("ws://test")
    
    # Act
    # "Start" two processes
    await sandbox.exec("command1", "bash")
    await sandbox.exec("command2", "bash")
    
    # Terminate the sandbox
    await sandbox.terminate()
    
    # Assert
    # Check that terminate was called on both processes
    process1.terminate.assert_awaited_once()
    process2.terminate.assert_awaited_once()