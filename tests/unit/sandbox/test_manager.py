import pytest
from src.sandbox.manager import SandboxManager
from src.sandbox.sandbox import FakeSandbox

def test_sandbox_manager_create():
    """Tests that the manager can create a sandbox."""
    mgr = SandboxManager()
    sandbox = mgr.create_sandbox(sandbox_id="test-123")
    
    assert sandbox is not None
    assert isinstance(sandbox, FakeSandbox)
    assert sandbox.sandbox_id == "test-123"

def test_sandbox_manager_get():
    """Tests that the manager can retrieve a created sandbox."""
    mgr = SandboxManager()
    sandbox1 = mgr.create_sandbox(sandbox_id="test-123")
    
    retrieved_sandbox = mgr.get_sandbox("test-123")
    assert retrieved_sandbox is sandbox1
    
    retrieved_sandbox_none = mgr.get_sandbox("non-existent")
    assert retrieved_sandbox_none is None

def test_sandbox_manager_delete():
    """Tests that the manager can delete a sandbox."""
    mgr = SandboxManager()
    mgr.create_sandbox(sandbox_id="test-123")
    
    assert mgr.get_sandbox("test-123") is not None
    mgr.delete_sandbox("test-123")
    assert mgr.get_sandbox("test-123") is None
