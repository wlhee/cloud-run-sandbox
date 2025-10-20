import pytest
from fastapi.testclient import TestClient
from src.server import app
from src.sandbox.fake import FakeSandbox, FakeSandboxConfig, ExecConfig
from src.sandbox.interface import SandboxCreationError, SandboxExecutionError, SandboxOperationError, SandboxCheckpointError, SandboxRestoreError
from src.sandbox.types import SandboxOutputEvent, OutputType, CodeLanguage, SandboxStateEvent
from src.sandbox.config import GCSConfig
from src.handlers import websocket
from src.sandbox.manager import SandboxManager
from unittest.mock import patch
from starlette.websockets import WebSocketDisconnect
import asyncio

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_manager(tmp_path):
    """
    Fixture to set up and tear down the manager for each test.
    This ensures that each test runs in isolation.
    """
    gcs_config = GCSConfig(
        metadata_mount_path=str(tmp_path),
        metadata_bucket="test-bucket",
        sandbox_checkpoint_mount_path=str(tmp_path),
        sandbox_checkpoint_bucket="test-bucket",
        filesystem_snapshot_mount_path=str(tmp_path),
        filesystem_snapshot_bucket="test-bucket",
    )
    manager = SandboxManager(gcs_config=gcs_config)
    websocket.manager = manager
    yield manager

@pytest.mark.asyncio
@patch('src.sandbox.manager.SandboxManager.create_sandbox')
async def test_create_interactive_session_success(mock_create_sandbox):
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
    await sandbox.create()
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
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello Python\n"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

        # 3. Execute second command (Bash)
        websocket.send_json({"language": "bash", "code": "echo 'Hello Bash'"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello Bash\n"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

    # Assert that the sandbox was created with the correct idle timeout
    mock_create_sandbox.assert_called_once_with(idle_timeout=120, enable_checkpoint=False, enable_sandbox_handoff=False, filesystem_snapshot_name=None)

@pytest.mark.asyncio
@patch('src.sandbox.manager.SandboxManager.create_sandbox')
async def test_create_sandbox_with_filesystem_snapshot(mock_create_sandbox):
    """
    Tests that a sandbox can be created with a filesystem snapshot.
    """
    # Arrange
    sandbox = FakeSandbox("snapshot-sandbox")
    await sandbox.create()
    mock_create_sandbox.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"filesystem_snapshot_name": "my-snapshot"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "snapshot-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

    # Assert that create_sandbox was called with the snapshot name
    mock_create_sandbox.assert_called_once_with(
        idle_timeout=300,
        enable_checkpoint=False,
        enable_sandbox_handoff=False,
        filesystem_snapshot_name="my-snapshot"
    )


@pytest.mark.asyncio
@patch('src.sandbox.manager.SandboxManager.create_sandbox')
async def test_create_sandbox_with_handoff(mock_create_sandbox):
    """
    Tests that a sandbox can be created with handoff enabled.
    """
    # Arrange
    sandbox = FakeSandbox("handoff-sandbox")
    await sandbox.create()
    mock_create_sandbox.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"enable_sandbox_handoff": True})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "handoff-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

    # Assert that create_sandbox was called with handoff enabled
    mock_create_sandbox.assert_called_once_with(
        idle_timeout=300,
        enable_checkpoint=False,
        enable_sandbox_handoff=True,
        filesystem_snapshot_name=None
    )


@pytest.mark.asyncio
@patch('src.sandbox.manager.SandboxManager.create_sandbox')
async def test_interactive_session_with_stdin(mock_create_sandbox):
    """
    Tests that stdin is correctly handled during an interactive session.
    """
    # Arrange
    config = FakeSandboxConfig(executions=[
        ExecConfig(
            expected_language=CodeLanguage.PYTHON,
            expected_code="input()",
            expected_stdin=["Hello from test"],
            output_stream=[SandboxOutputEvent(type=OutputType.STDOUT, data="Hello from test\n")]
        )
    ])
    sandbox = FakeSandbox("stdin-sandbox", config=config)
    await sandbox.create()
    mock_create_sandbox.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        # 1. Send initial config and receive confirmation
        websocket.send_json({"idle_timeout": 120})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "stdin-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        # 2. Execute command
        websocket.send_json({"language": "python", "code": "input()"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}

        # 3. Write to stdin
        websocket.send_json({"event": "stdin", "data": "Hello from test"})

        # 4. Receive output and completion
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello from test\n"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

@patch('src.sandbox.manager.SandboxManager.create_sandbox')
def test_create_sandbox_creation_error(mock_create_sandbox):
    """
    Tests that a sandbox creation error is handled gracefully.
    """
    # Arrange
    mock_create_sandbox.side_effect = SandboxCreationError("Failed to create sandbox")

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"idle_timeout": 120})
        
        # Check for the status updates and the error message
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATION_ERROR"}
        assert websocket.receive_json() == {"event": "error", "message": "Failed to create sandbox"}
        
        # The connection should be closed after the error
        with pytest.raises(WebSocketDisconnect) as e:
            websocket.receive_json()
        assert e.value.code == 4000

@patch('src.sandbox.manager.SandboxManager.create_sandbox')
@patch('src.sandbox.manager.SandboxManager.get_sandbox')
def test_create_and_attach_session(mock_get_sandbox, mock_create_sandbox):
    """
    Tests that a client can create a sandbox, disconnect, and another client
    can attach to it.
    """
    # Arrange
    sandbox = FakeSandbox("test-sandbox")
    mock_create_sandbox.return_value = sandbox
    mock_get_sandbox.return_value = sandbox

    # Act & Assert
    # 1. Create the sandbox
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"idle_timeout": 120})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "test-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

    # 2. Attach to the sandbox
    with client.websocket_connect("/attach/test-sandbox") as websocket:
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

@patch('src.sandbox.manager.SandboxManager.get_sandbox')
def test_attach_to_in_use_sandbox(mock_get_sandbox):
    """
    Tests that attaching to a sandbox that is already in use fails.
    """
    # Arrange
    sandbox = FakeSandbox("test-sandbox")
    sandbox.is_attached = True
    mock_get_sandbox.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/attach/test-sandbox") as websocket:
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_IN_USE"}
        with pytest.raises(WebSocketDisconnect) as e:
            websocket.receive_json()
        assert e.value.code == 1011

@pytest.mark.asyncio
@patch('src.sandbox.manager.SandboxManager.create_sandbox')
async def test_sandbox_execution_error(mock_create_sandbox):
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
    await sandbox.create()
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

@pytest.mark.asyncio
@patch('src.sandbox.manager.SandboxManager.create_sandbox')
async def test_invalid_message_format(mock_create_sandbox):
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
    await sandbox.create()
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
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        assert websocket.receive_json() == {"event": "stdout", "data": "still open\n"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

@pytest.mark.asyncio
@patch('src.sandbox.manager.SandboxManager.create_sandbox')
async def test_unsupported_language(mock_create_sandbox):
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
    await sandbox.create()
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
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        assert websocket.receive_json() == {"event": "stdout", "data": "still open\n"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

@patch('src.sandbox.manager.SandboxManager.restore_sandbox')
@patch('src.sandbox.manager.SandboxManager.get_sandbox')
def test_attach_restore_sandbox(mock_get_sandbox, mock_restore_sandbox):
    """
    Tests that a client can attach to a sandbox that has been checkpointed,
    triggering a restore.
    """
    # Arrange
    sandbox = FakeSandbox("test-sandbox")
    mock_get_sandbox.return_value = None # Simulate cache miss
    mock_restore_sandbox.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/attach/test-sandbox") as websocket:
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RESTORING"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

def test_create_with_checkpoint_fails_if_not_configured(setup_manager):
    """
    Tests that creating a sandbox with checkpointing enabled fails if the
    manager is not configured with a persistence path.
    """
    setup_manager.gcs_config = None
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"enable_checkpoint": True})
        
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATION_ERROR"}
        assert websocket.receive_json() == {"event": "error", "message": "Checkpointing is not enabled on the server."}
        
        with pytest.raises(WebSocketDisconnect) as e:
            websocket.receive_json()
        assert e.value.code == 4000

@pytest.mark.asyncio
@patch('src.sandbox.manager.SandboxManager.checkpoint_sandbox')
@patch('src.sandbox.manager.SandboxManager.create_sandbox')
async def test_sandbox_checkpoint(mock_create_sandbox, mock_checkpoint_sandbox):
    """
    Tests that the 'checkpoint' action is correctly handled.
    """
    # Arrange
    sandbox = FakeSandbox("test-sandbox")
    mock_create_sandbox.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"idle_timeout": 120, "enable_checkpoint": True})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "test-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}
        websocket.send_json({"action": "checkpoint"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINTING"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINTED"}
        with pytest.raises(WebSocketDisconnect) as e:
            websocket.receive_json()
        assert e.value.code == 1000

@pytest.mark.asyncio
@patch('src.sandbox.manager.SandboxManager.checkpoint_sandbox')
@patch('src.sandbox.manager.SandboxManager.create_sandbox')
async def test_sandbox_checkpoint_failure(mock_create_sandbox, mock_checkpoint_sandbox):
    """
    Tests that a failure during checkpointing is handled gracefully.
    """
    # Arrange
    sandbox = FakeSandbox("test-sandbox")
    mock_create_sandbox.return_value = sandbox
    mock_checkpoint_sandbox.side_effect = SandboxCheckpointError("Checkpoint failed")

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"idle_timeout": 120, "enable_checkpoint": True})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "test-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}
        websocket.send_json({"action": "checkpoint"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINTING"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINT_ERROR"}
        assert websocket.receive_json() == {"event": "error", "message": "Failed to checkpoint sandbox test-sandbox: Checkpoint failed"}
        with pytest.raises(WebSocketDisconnect) as e:
            websocket.receive_json()
        assert e.value.code == 4000

@patch('src.sandbox.manager.SandboxManager.restore_sandbox')
def test_attach_restore_sandbox_not_found(mock_restore_sandbox):
    """
    Tests that a failure to find a sandbox to restore is handled gracefully.
    """
    # Arrange
    mock_restore_sandbox.return_value = None

    # Act & Assert
    with client.websocket_connect("/attach/test-sandbox") as websocket:
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RESTORING"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_NOT_FOUND"}
        with pytest.raises(WebSocketDisconnect) as e:
            websocket.receive_json()
        assert e.value.code == 1011

@patch('src.sandbox.manager.SandboxManager.restore_sandbox')
def test_attach_restore_sandbox_failure(mock_restore_sandbox):
    """
    Tests that a failure during restore is handled gracefully.
    """
    # Arrange
    mock_restore_sandbox.side_effect = SandboxRestoreError("Restore failed")

    # Act & Assert
    with client.websocket_connect("/attach/test-sandbox") as websocket:
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RESTORING"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RESTORE_ERROR"}
        assert websocket.receive_json() == {"event": "error", "message": "Failed to restore sandbox test-sandbox: Restore failed"}
        with pytest.raises(WebSocketDisconnect) as e:
            websocket.receive_json()
        assert e.value.code == 4000

@pytest.mark.asyncio
@patch('src.sandbox.manager.SandboxManager.snapshot_filesystem')
@patch('src.sandbox.manager.SandboxManager.create_sandbox')
async def test_snapshot_filesystem(mock_create_sandbox, mock_snapshot_filesystem):
    """
    Tests that the 'snapshot_filesystem' action is correctly handled.
    """
    # Arrange
    sandbox = FakeSandbox("test-sandbox")
    mock_create_sandbox.return_value = sandbox

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"idle_timeout": 120})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "test-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        websocket.send_json({"action": "snapshot_filesystem", "name": "my-snapshot"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_FILESYSTEM_SNAPSHOT_CREATING"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_FILESYSTEM_SNAPSHOT_CREATED"}

    mock_snapshot_filesystem.assert_called_once_with("test-sandbox", "my-snapshot")

@pytest.mark.asyncio
@patch('src.sandbox.manager.SandboxManager.create_sandbox')
async def test_snapshot_filesystem_not_configured(mock_create_sandbox, setup_manager):
    """
    Tests that taking a filesystem snapshot fails if the feature is not configured.
    """
    # Arrange
    sandbox = FakeSandbox("test-sandbox")
    mock_create_sandbox.return_value = sandbox
    setup_manager.gcs_config = None

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"idle_timeout": 120})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "test-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        websocket.send_json({"action": "snapshot_filesystem", "name": "my-snapshot"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_FILESYSTEM_SNAPSHOT_CREATING"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_FILESYSTEM_SNAPSHOT_ERROR"}
        assert websocket.receive_json() == {"event": "error", "message": "Failed to snapshot filesystem for sandbox test-sandbox: Filesystem snapshot is not enabled on the server."}
@pytest.mark.asyncio
@patch('src.sandbox.manager.SandboxManager.snapshot_filesystem')
@patch('src.sandbox.manager.SandboxManager.create_sandbox')
async def test_snapshot_filesystem_error(mock_create_sandbox, mock_snapshot_filesystem):
    """
    Tests that an error during filesystem snapshotting is handled gracefully.
    """
    # Arrange
    sandbox = FakeSandbox("test-sandbox")
    mock_create_sandbox.return_value = sandbox
    mock_snapshot_filesystem.side_effect = SandboxOperationError("Snapshot failed")

    # Act & Assert
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"idle_timeout": 120})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
        assert websocket.receive_json() == {"event": "sandbox_id", "sandbox_id": "test-sandbox"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        websocket.send_json({"action": "snapshot_filesystem", "name": "my-snapshot"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_FILESYSTEM_SNAPSHOT_CREATING"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_FILESYSTEM_SNAPSHOT_ERROR"}
        assert websocket.receive_json() == {"event": "error", "message": "Failed to snapshot filesystem for sandbox test-sandbox: Snapshot failed"}
