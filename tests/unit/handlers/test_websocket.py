import pytest
from fastapi.testclient import TestClient
from src.server import app
from src.sandbox.fake import FakeSandbox, FakeSandboxConfig, ExecConfig
from src.sandbox.interface import SandboxCreationError, SandboxExecutionError
from src.sandbox.types import SandboxOutputEvent, OutputType, CodeLanguage, SandboxStateEvent
from unittest.mock import patch
from starlette.websockets import WebSocketDisconnect

client = TestClient(app)

@patch('src.handlers.websocket.sandbox_manager.create_sandbox')
def test_create_interactive_session_success(mock_create_sandbox):
    """
    Tests the successful creation of an interactive sandbox session,
    executing multiple commands.
    """
    # Arrange
    config = FakeSandboxConfig(executions=[
        ExecConfig(
            expected_language=CodeLanguage.PYTHON,
            expected_code="print('Hello Python')",
            output_stream=[SandboxOutputEvent(type=OutputType.STDOUT, data="Hello Python\n")]
        ),
        ExecConfig(
            expected_language=CodeLanguage.BASH,
            expected_code="echo 'Hello Bash'",
            output_stream=[SandboxOutputEvent(type=OutputType.STDOUT, data="Hello Bash\n")]
        )
    ])
    sandbox = FakeSandbox("interactive-sandbox", config=config)
    mock_create_sandbox.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        # 1. Send initial config and receive confirmation
        websocket.send_json({"idle_timeout": 120})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "interactive-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        # 2. Execute first command (Python)
        websocket.send_json({"language": "python", "code": "print('Hello Python')"})
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello Python\n"}

        # 3. Execute second command (Bash)
        websocket.send_json({"language": "bash", "code": "echo 'Hello Bash'"})
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello Bash\n"}

    # Assert that the sandbox was created with the correct idle timeout
    mock_create_sandbox.assert_called_once_with(idle_timeout=120)

@patch('src.handlers.websocket.sandbox_manager.create_sandbox')
def test_create_sandbox_creation_error(mock_create_sandbox):
    """
    Tests that a sandbox creation error is handled gracefully.
    """
    # Arrange
    mock_create_sandbox.side_effect = SandboxCreationError("Failed to create sandbox")

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"idle_timeout": 120})
        
        # Check for the status updates
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATION_ERROR"}
        
        # The connection should be closed after the error
        with pytest.raises(WebSocketDisconnect) as e:
            websocket.receive_json()
        assert e.value.code == 4000

@patch('src.handlers.websocket.sandbox_manager.create_sandbox')
def test_sandbox_execution_error(mock_create_sandbox):
    """
    Tests that a sandbox operation error is handled gracefully.
    """
    # Arrange
    config = FakeSandboxConfig(executions=[
        ExecConfig(
            expected_language=CodeLanguage.PYTHON,
            expected_code="print('will fail')",
            exec_error=SandboxExecutionError
        )
    ])
    sandbox = FakeSandbox("test-sandbox", config=config)
    mock_create_sandbox.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"idle_timeout": 120})
        
        # Initial handshake
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "test-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        # Send code that will trigger the error
        websocket.send_json({"language": "python", "code": "print('will fail')"})

        # Check for the error message
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_ERROR"}
        assert websocket.receive_json() == {"event": "error", "message": "Fake sandbox failed to execute as configured."}
        
        # The connection should remain open for subsequent commands
        # (This part of the test is not fully implemented as the FakeSandbox
        # is configured for a single execution)
        # websocket.send_json({"language": "python", "code": "print('still open')"})

@patch('src.handlers.websocket.sandbox_manager.create_sandbox')
def test_invalid_message_format(mock_create_sandbox):
    """
    Tests that the server handles an invalid message format gracefully.
    """
    # Arrange
    config = FakeSandboxConfig(executions=[
        ExecConfig(
            expected_language=CodeLanguage.PYTHON,
            expected_code="print('still open')",
            output_stream=[SandboxOutputEvent(type=OutputType.STDOUT, data="still open\n")]
        )
    ])
    sandbox = FakeSandbox("test-sandbox", config=config)
    mock_create_sandbox.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"idle_timeout": 120})
        
        # Initial handshake
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "test-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        # Send a malformed message
        websocket.send_json({"invalid_key": "some_value"})

        # Check for the error message
        supported_languages = ", ".join([lang.value for lang in CodeLanguage])
        expected_error = (
            "Invalid message format. 'language' and 'code' fields are required. "
            f"Supported languages are: {supported_languages}"
        )
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_ERROR"}
        assert websocket.receive_json() == {"event": "error", "message": expected_error}

        # The connection should remain open
        websocket.send_json({"language": "python", "code": "print('still open')"})
        assert websocket.receive_json() == {"event": "stdout", "data": "still open\n"}

@patch('src.handlers.websocket.sandbox_manager.create_sandbox')
def test_unsupported_language(mock_create_sandbox):
    """
    Tests that the server handles an unsupported language gracefully.
    """
    # Arrange
    config = FakeSandboxConfig(executions=[
        ExecConfig(
            expected_language=CodeLanguage.PYTHON,
            expected_code="print('still open')",
            output_stream=[SandboxOutputEvent(type=OutputType.STDOUT, data="still open\n")]
        )
    ])
    sandbox = FakeSandbox("test-sandbox", config=config)
    mock_create_sandbox.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"idle_timeout": 120})
        
        # Initial handshake
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "test-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        # Send a message with an unsupported language
        websocket.send_json({"language": "unsupported", "code": "some code"})

        # Check for the error message
        supported_languages = ", ".join([lang.value for lang in CodeLanguage])
        expected_error = (
            "Invalid message format. 'language' and 'code' fields are required. "
            f"Supported languages are: {supported_languages}"
        )
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_ERROR"}
        assert websocket.receive_json() == {"event": "error", "message": expected_error}

        # The connection should remain open
        websocket.send_json({"language": "python", "code": "print('still open')"})
        assert websocket.receive_json() == {"event": "stdout", "data": "still open\n"}
