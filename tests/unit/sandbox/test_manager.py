import pytest
from src.sandbox.manager import SandboxManager
from src.sandbox.fake import FakeSandbox, FakeSandboxConfig
from src.sandbox.interface import SandboxCreationError
from unittest.mock import patch, ANY
import asyncio

pytestmark = pytest.mark.asyncio

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_manager_create_and_get_sandbox(mock_create_instance):
    """
    Tests that the manager can create, initialize, and retrieve a sandbox.
    """
    # Arrange: Create a real FakeSandbox and configure the factory mock to return it.
    sandbox_to_return = FakeSandbox("test-123")
    mock_create_instance.return_value = sandbox_to_return
    
    mgr = SandboxManager()
    
    # Act
    sandbox = await mgr.create_sandbox(sandbox_id="test-123")
    
    # Assert
    mock_create_instance.assert_called_once_with("test-123", config=ANY)
    assert mgr.get_sandbox("test-123") is sandbox_to_return

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_manager_delete_sandbox(mock_create_instance):
    """Tests that the manager can delete a sandbox."""
    # Arrange
    sandbox = FakeSandbox("test-123")
    mock_create_instance.return_value = sandbox
    mgr = SandboxManager()
    
    delete_event = asyncio.Event()
    await mgr.create_sandbox(
        sandbox_id="test-123",
        delete_callback=lambda sid: delete_event.set()
    )
    
    # Act
    assert mgr.get_sandbox("test-123") is not None
    await mgr.delete_sandbox("test-123")
    
    # Assert
    # Wait for the callback to be fired
    await asyncio.wait_for(delete_event.wait(), timeout=1)
    assert mgr.get_sandbox("test-123") is None

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_manager_create_sandbox_failure(mock_create_instance):
    """
    Tests that the manager handles a sandbox creation failure correctly.
    """
    # Arrange: Configure a real FakeSandbox to fail on create.
    config = FakeSandboxConfig(create_should_fail=True)
    sandbox_that_will_fail = FakeSandbox("test-fail", config=config)
    mock_create_instance.return_value = sandbox_that_will_fail
    
    mgr = SandboxManager()

    # Act & Assert
    with pytest.raises(SandboxCreationError):
        await mgr.create_sandbox(sandbox_id="test-fail")
    
    # Ensure the failed sandbox was not added to the manager
    assert mgr.get_sandbox("test-fail") is None

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_idle_cleanup(mock_create_instance):
    """Tests that an idle sandbox is automatically deleted."""
    # Arrange
    sandbox = FakeSandbox("idle-sandbox")
    mock_create_instance.return_value = sandbox
    mgr = SandboxManager()
    delete_event = asyncio.Event()
    
    # Act
    await mgr.create_sandbox(
        sandbox_id="idle-sandbox",
        idle_timeout=0.1,
        delete_callback=lambda sid: delete_event.set()
    )
    
    # Assert
    assert "idle-sandbox" in mgr._sandboxes
    
    # Wait for the idle cleanup to trigger the deletion and the callback
    await asyncio.wait_for(delete_event.wait(), timeout=1)
    
    assert mgr.get_sandbox("idle-sandbox") is None

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_update_activity_resets_timer(mock_create_instance):
    """Tests that updating activity resets the idle timer."""
    # Arrange
    sandbox = FakeSandbox("active-sandbox")
    mock_create_instance.return_value = sandbox
    mgr = SandboxManager()
    delete_event = asyncio.Event()

    # Act
    await mgr.create_sandbox(
        sandbox_id="active-sandbox",
        idle_timeout=0.2,
        delete_callback=lambda sid: delete_event.set()
    )
    
    # Update activity and ensure the sandbox is not deleted prematurely
    mgr.update_sandbox_activity("active-sandbox")
    await asyncio.sleep(0.1)
    assert not delete_event.is_set()
    assert mgr.get_sandbox("active-sandbox") is not None

    # Wait for the new timeout to fire
    await asyncio.wait_for(delete_event.wait(), timeout=1)
    assert mgr.get_sandbox("active-sandbox") is None

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_delete_all_sandboxes(mock_create_instance):
    """Tests that all sandboxes are deleted."""
    # Arrange
    sandbox1 = FakeSandbox("sandbox1")
    sandbox2 = FakeSandbox("sandbox2")
    mock_create_instance.side_effect = [sandbox1, sandbox2]
    mgr = SandboxManager()

    delete_event1 = asyncio.Event()
    delete_event2 = asyncio.Event()

    await mgr.create_sandbox(
        sandbox_id="sandbox1",
        delete_callback=lambda sid: delete_event1.set()
    )
    await mgr.create_sandbox(
        sandbox_id="sandbox2",
        delete_callback=lambda sid: delete_event2.set()
    )

    # Act
    await mgr.delete_all_sandboxes()
    await asyncio.gather(delete_event1.wait(), delete_event2.wait())

    # Assert
    assert mgr.get_sandbox("sandbox1") is None
    assert mgr.get_sandbox("sandbox2") is None
