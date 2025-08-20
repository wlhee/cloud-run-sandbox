import pytest
from src.sandbox.manager import SandboxManager
from src.sandbox.fake import FakeSandbox, FakeSandboxConfig
from src.sandbox.interface import SandboxCreationError
from unittest.mock import patch

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
    mock_create_instance.assert_called_once_with("test-123")
    assert mgr.get_sandbox("test-123") is sandbox_to_return

async def test_manager_delete_sandbox():
    """Tests that the manager can delete a sandbox."""
    # This test can use a real FakeSandbox without any mocking.
    mgr = SandboxManager()
    # Manually insert the sandbox to bypass the factory for this test.
    sandbox = FakeSandbox("test-123")
    mgr._sandboxes["test-123"] = sandbox
    
    assert mgr.get_sandbox("test-123") is not None
    await mgr.delete_sandbox("test-123")
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