import pytest
from fastapi.testclient import TestClient
from src.server import app
from src.sandbox.fake import FakeSandbox, FakeSandboxConfig
from src.sandbox.interface import SandboxCreationError, SandboxStartError
from src.sandbox.events import SandboxOutputEvent, OutputType
from unittest.mock import patch

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

# We will add tests for the attach endpoint later.