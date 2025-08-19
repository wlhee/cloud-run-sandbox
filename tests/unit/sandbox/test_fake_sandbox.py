import pytest
import asyncio
from unittest.mock import AsyncMock
from src.sandbox.sandbox import FakeSandbox

pytestmark = pytest.mark.asyncio

@pytest.fixture
def mock_websocket():
    """Fixture to create a mock websocket."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.close = AsyncMock()
    return ws

async def test_fake_sandbox_lifecycle(mock_websocket):
    """
    Tests the full create -> start -> stop -> delete lifecycle of the FakeSandbox.
    """
    sandbox_id = "fake-123"
    sandbox = FakeSandbox(sandbox_id)

    # Test create
    await sandbox.create("print('hello')")
    assert sandbox._code == "print('hello')"

    # Test start
    await sandbox.start(mock_websocket)
    assert sandbox.is_running
    assert sandbox._task is not None
    mock_websocket.send_json.assert_any_call({"event": "status_update", "status": "RUNNING"})

    # Test stop
    await sandbox.stop()
    assert not sandbox.is_running
    assert sandbox._task is None
    mock_websocket.close.assert_awaited_once_with(code=1000)

    # Test delete
    # Re-start the sandbox to test that delete also stops it
    await sandbox.start(mock_websocket)
    await sandbox.delete()
    assert not sandbox.is_running
    assert sandbox._task is None
