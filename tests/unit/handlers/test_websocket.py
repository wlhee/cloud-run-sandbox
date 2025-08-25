import pytest
from fastapi.testclient import TestClient
from src.server import app
from src.sandbox.fake import FakeSandbox, FakeSandboxConfig
from src.sandbox.interface import SandboxCreationError, SandboxStartError
from src.sandbox.types import SandboxOutputEvent, OutputType
from unittest.mock import patch, MagicMock, AsyncMock

client = TestClient(app)

@patch('src.sandbox.manager.factory.create_sandbox_instance')
def test_create_websocket_success(mock_create_instance):
    """
    Tests the successful creation of a sandbox and streaming of multiple
    stdout and stderr messages.
    """
    # Arrange: Configure a FakeSandbox with a mixed stream of output
    output_stream = [
        SandboxOutputEvent(type=OutputType.STDOUT, data="First line\n"),
        SandboxOutputEvent(type=OutputType.STDERR, data="An error message\n"),
        SandboxOutputEvent(type=OutputType.STDOUT, data="Second line\n"),
    ]
    config = FakeSandboxConfig(output_messages=output_stream)
    sandbox = FakeSandbox("fake-sandbox-123", config=config)
    mock_create_instance.return_value = sandbox
    
    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "fake-sandbox-123"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}
        
        # Verify the full output stream
        assert websocket.receive_json() == {"event": "stdout", "data": "First line\n"}
        assert websocket.receive_json() == {"event": "stderr", "data": "An error message\n"}
        assert websocket.receive_json() == {"event": "stdout", "data": "Second line\n"}

@patch('src.sandbox.manager.factory.create_sandbox_instance')
def test_create_websocket_creation_error(mock_create_instance):
    """Tests the case where the sandbox fails to create."""
    # Arrange: Configure the FakeSandbox to fail on create
    config = FakeSandboxConfig(create_should_fail=True)
    sandbox = FakeSandbox("fake-sandbox-error", config=config)
    mock_create_instance.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATION_ERROR"}
        assert "Fake sandbox failed to create as configured." in websocket.receive_json()["message"]

@patch('src.sandbox.manager.factory.create_sandbox_instance')
def test_create_websocket_start_error(mock_create_instance):
    """Tests the case where the sandbox fails to start."""
    # Arrange: Configure the FakeSandbox to fail on start
    config = FakeSandboxConfig(start_should_fail=True)
    sandbox = FakeSandbox("fake-sandbox-error", config=config)
    mock_create_instance.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "fake-sandbox-error"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_START_ERROR"}
        assert "Fake sandbox failed to start as configured." in websocket.receive_json()["message"]

@patch('src.handlers.websocket.sandbox_manager')
def test_attach_websocket_success(mock_manager):
    """Tests successfully attaching to an existing sandbox."""
    # Arrange
    output_stream = [SandboxOutputEvent(type=OutputType.STDOUT, data="existing output")]
    config = FakeSandboxConfig(output_messages=output_stream)
    sandbox = FakeSandbox("existing-sandbox", config=config)
    mock_manager.get_sandbox.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/attach/existing-sandbox") as websocket:
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}
        assert websocket.receive_json() == {"event": "stdout", "data": "existing output"}
    
    mock_manager.get_sandbox.assert_called_once_with("existing-sandbox")
    mock_manager.delete_sandbox.assert_not_called()

@patch('src.handlers.websocket.sandbox_manager')
def test_attach_websocket_not_found(mock_manager):
    """Tests attaching to a non-existent sandbox."""
    # Arrange
    mock_manager.get_sandbox.return_value = None

    # Act & Assert
    with client.websocket_connect("/attach/not-found-sandbox") as websocket:
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_NOT_FOUND"}

    mock_manager.get_sandbox.assert_called_once_with("not-found-sandbox")

@patch('src.handlers.websocket.sandbox_manager')
def test_create_disconnect_attach(mock_manager):
    """
    Tests that a sandbox persists after the creating client disconnects
    and can be successfully attached to by a new client.
    """
    # Arrange
    output_stream = [SandboxOutputEvent(type=OutputType.STDOUT, data="final output")]
    config = FakeSandboxConfig(output_messages=output_stream)
    sandbox = FakeSandbox("persistent-sandbox", config=config)
    
    # Configure the mock manager with the correct async/sync methods
    mock_manager.create_sandbox = AsyncMock(return_value=sandbox)
    mock_manager.get_sandbox.return_value = sandbox

    # Act 1: Create the sandbox and immediately disconnect
    with client.websocket_connect("/create") as websocket:
        assert websocket.receive_json()["status"] == "SANDBOX_CREATING"
        assert websocket.receive_json()["sandbox_id"] == "persistent-sandbox"
        assert websocket.receive_json()["status"] == "SANDBOX_RUNNING"
        # The first client consumes the output
        assert websocket.receive_json()["data"] == "final output"
    
    # Assert that the sandbox was NOT deleted on disconnect
    mock_manager.delete_sandbox.assert_not_called()

    # Act 2: Attach to the orphaned sandbox
    with client.websocket_connect("/attach/persistent-sandbox") as websocket:
        assert websocket.receive_json()["status"] == "SANDBOX_RUNNING"
        # The second client should also receive the full output stream
        assert websocket.receive_json()["data"] == "final output"

    # Assert that the sandbox was NOT deleted after the attaching client disconnected
    mock_manager.delete_sandbox.assert_not_called()
