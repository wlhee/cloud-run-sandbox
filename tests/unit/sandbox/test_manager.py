import pytest
from src.sandbox.config import GCSConfig
from src.sandbox.manager import SandboxManager
from src.sandbox.fake import FakeSandbox, FakeSandboxConfig
from src.sandbox.interface import SandboxCreationError, SandboxOperationError, SandboxSnapshotFilesystemError, SandboxRestoreError
from unittest.mock import patch, ANY
import asyncio
import os
import json
import time

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
    """
    Tests that an idle sandbox is automatically deleted.
    """
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
async def test_reset_idle_timer(mock_create_instance):
    """Tests that resetting the idle timer prevents cleanup."""
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
    
    # Reset timer and ensure the sandbox is not deleted prematurely
    mgr.reset_idle_timer("active-sandbox")
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

# --- Checkpoint and Restore Tests ---

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_create_with_checkpoint_enabled(mock_create_instance, tmp_path):
    """
    Tests that creating a sandbox with checkpointing enabled creates the
    necessary directory and metadata file.
    """
    # Arrange
    sandbox = FakeSandbox("checkpoint-sandbox")
    mock_create_instance.return_value = sandbox
    mgr = SandboxManager()
    mgr.gcs_config = GCSConfig(sandbox_checkpoint_mount_path=str(tmp_path))
    # Act
    await mgr.create_sandbox(sandbox_id="checkpoint-sandbox", enable_checkpoint=True, idle_timeout=300)
    
    # Assert
    sandbox_dir = tmp_path / "checkpoint-sandbox"
    checkpoints_dir = sandbox_dir / "checkpoints"
    metadata_path = sandbox_dir / "metadata.json"
    assert checkpoints_dir.is_dir()
    assert metadata_path.is_file()
    with open(metadata_path, "r") as f:
        metadata = json.load(f)
    assert metadata["idle_timeout"] == 300

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_create_with_checkpoint_fails_if_not_configured(mock_create_instance):
    """
    Tests that creating a sandbox with checkpointing enabled fails if the
    manager is not configured with a persistence path.
    """
    mgr = SandboxManager() # No checkpoint_and_restore_path
    with pytest.raises(SandboxCreationError, match="Checkpointing is not enabled on the server."):
        await mgr.create_sandbox(sandbox_id="test", enable_checkpoint=True)

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_checkpoint_sandbox(mock_create_instance, tmp_path):
    """
    Tests that checkpointing a sandbox calls the instance's checkpoint method,
    updates the metadata, and deletes the local instance.
    """
    # Arrange
    sandbox = FakeSandbox("checkpoint-sandbox")
    mock_create_instance.return_value = sandbox
    mgr = SandboxManager()
    mgr.gcs_config = GCSConfig(sandbox_checkpoint_mount_path=str(tmp_path))
    await mgr.create_sandbox(sandbox_id="checkpoint-sandbox", enable_checkpoint=True, idle_timeout=300)
    
    # Act
    await mgr.checkpoint_sandbox("checkpoint-sandbox")
    
    # Assert
    checkpoints_dir = tmp_path / "checkpoint-sandbox" / "checkpoints"
    latest_path = checkpoints_dir / "latest"
    assert latest_path.is_file()

    with open(latest_path, "r") as f:
        latest_checkpoint_name = f.read().strip()
    
    checkpoint_file = checkpoints_dir / latest_checkpoint_name
    assert checkpoint_file.is_file()

    metadata_path = tmp_path / "checkpoint-sandbox" / "metadata.json"
    with open(metadata_path, "r") as f:
        metadata = json.load(f)
    assert metadata["idle_timeout"] == 300 # Ensure idle_timeout is preserved
    assert mgr.get_sandbox("checkpoint-sandbox") is None # Should be removed from memory

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_restore_sandbox(mock_create_instance, tmp_path):
    """
    Tests that restore_sandbox restores a sandbox from a checkpoint if it's not
    in memory.
    """
    # Arrange
    sandbox_id = "restore-sandbox"
    checkpoints_dir = tmp_path / sandbox_id / "checkpoints"
    os.makedirs(checkpoints_dir)
    checkpoint_file = checkpoints_dir / "checkpoint_123.img"
    checkpoint_file.touch()
    latest_path = checkpoints_dir / "latest"
    with open(latest_path, "w") as f:
        f.write("checkpoint_123.img")
    metadata_path = tmp_path / sandbox_id / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump({"idle_timeout": 180}, f)

    restored_sandbox = FakeSandbox(sandbox_id)
    mock_create_instance.return_value = restored_sandbox
    
    mgr = SandboxManager()
    mgr.gcs_config = GCSConfig(sandbox_checkpoint_mount_path=str(tmp_path))
    
    # Act
    sandbox = await mgr.restore_sandbox(sandbox_id)
    
    # Assert
    assert sandbox is restored_sandbox
    assert mgr.get_sandbox(sandbox_id) is restored_sandbox # Should be in memory now
    assert mgr._sandboxes[sandbox_id].idle_timeout == 180 # Check that idle_timeout was restored

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_checkpoint_sandbox_fails(mock_create_instance, tmp_path):
    """
    Tests that the manager correctly handles a failure during checkpointing.
    """
    # Arrange
    config = FakeSandboxConfig(checkpoint_should_fail=True)
    sandbox = FakeSandbox("fail-sandbox", config=config)
    mock_create_instance.return_value = sandbox
    mgr = SandboxManager()
    mgr.gcs_config = GCSConfig(sandbox_checkpoint_mount_path=str(tmp_path))
    await mgr.create_sandbox(sandbox_id="fail-sandbox", enable_checkpoint=True)
    
    # Act & Assert
    with pytest.raises(SandboxOperationError, match="Fake sandbox failed to checkpoint as configured."):
        await mgr.checkpoint_sandbox("fail-sandbox")
    
    # Ensure the sandbox was NOT deleted from memory on failure
    assert mgr.get_sandbox("fail-sandbox") is not None

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_restore_sandbox_fails(mock_create_instance, tmp_path):
    """
    Tests that the manager handles a failure during restore.
    """
    # Arrange
    sandbox_id = "fail-restore"
    checkpoints_dir = tmp_path / sandbox_id / "checkpoints"
    os.makedirs(checkpoints_dir)
    checkpoint_file = checkpoints_dir / "checkpoint_123.img"
    checkpoint_file.touch()
    latest_path = checkpoints_dir / "latest"
    with open(latest_path, "w") as f:
        f.write("checkpoint_123.img")

    config = FakeSandboxConfig(restore_should_fail=True)
    sandbox_that_will_fail = FakeSandbox(sandbox_id, config=config)
    mock_create_instance.return_value = sandbox_that_will_fail
    
    mgr = SandboxManager()
    mgr.gcs_config = GCSConfig(sandbox_checkpoint_mount_path=str(tmp_path))
    
    # Act
    with pytest.raises(SandboxRestoreError, match="Failed to restore sandbox fail-restore"):
        await mgr.restore_sandbox(sandbox_id)
    
    # Assert
    assert mgr.get_sandbox(sandbox_id) is None # Should not be in memory

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_restore_sandbox_starts_idle_timer(mock_create_instance, tmp_path):
    """
    Tests that a restored sandbox with an idle_timeout has its cleanup
    task started.
    """
    # Arrange
    sandbox_id = "restore-timer-sandbox"
    checkpoints_dir = tmp_path / sandbox_id / "checkpoints"
    os.makedirs(checkpoints_dir)
    checkpoint_file = checkpoints_dir / "checkpoint_123.img"
    checkpoint_file.touch()
    latest_path = checkpoints_dir / "latest"
    with open(latest_path, "w") as f:
        f.write("checkpoint_123.img")
    metadata_path = tmp_path / sandbox_id / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump({"idle_timeout": 0.1}, f)

    restored_sandbox = FakeSandbox(sandbox_id)
    mock_create_instance.return_value = restored_sandbox
    
    mgr = SandboxManager()
    mgr.gcs_config = GCSConfig(sandbox_checkpoint_mount_path=str(tmp_path))
    delete_event = asyncio.Event()
    
    # Act
    sandbox = await mgr.restore_sandbox(sandbox_id, delete_callback=lambda sid: delete_event.set())
    assert sandbox is not None
    
    # Assert
    await asyncio.wait_for(delete_event.wait(), timeout=1)
    assert mgr.get_sandbox(sandbox_id) is None
@patch('src.sandbox.factory.create_sandbox_instance')
async def test_checkpoint_restore_checkpoint_restore(mock_create_instance, tmp_path):
    """
    Tests the full lifecycle of checkpoint -> restore -> checkpoint -> restore
    to ensure multiple checkpoints are handled correctly.
    """
    sandbox_id = "multi-checkpoint-sandbox"
    mgr = SandboxManager()
    mgr.gcs_config = GCSConfig(sandbox_checkpoint_mount_path=str(tmp_path))

    # --- Create and First Checkpoint ---
    mock_create_instance.return_value = FakeSandbox(sandbox_id)
    await mgr.create_sandbox(sandbox_id=sandbox_id, enable_checkpoint=True)
    await mgr.checkpoint_sandbox(sandbox_id)
    
    checkpoints_dir = tmp_path / sandbox_id / "checkpoints"
    latest_path = checkpoints_dir / "latest"
    assert latest_path.is_file()
    with open(latest_path, "r") as f:
        first_checkpoint_name = f.read().strip()
    assert (checkpoints_dir / first_checkpoint_name).is_file()
    assert mgr.get_sandbox(sandbox_id) is None

    # --- First Restore ---
    restored_sandbox_1 = FakeSandbox(sandbox_id)
    mock_create_instance.return_value = restored_sandbox_1
    sandbox_1 = await mgr.restore_sandbox(sandbox_id)
    assert sandbox_1 is restored_sandbox_1
    assert mgr.get_sandbox(sandbox_id) is restored_sandbox_1

    # --- Second Checkpoint ---
    await mgr.checkpoint_sandbox(sandbox_id)
    assert latest_path.is_file()
    with open(latest_path, "r") as f:
        second_checkpoint_name = f.read().strip()
    assert (checkpoints_dir / second_checkpoint_name).is_file()
    assert second_checkpoint_name != first_checkpoint_name
    assert mgr.get_sandbox(sandbox_id) is None

    # --- Second Restore ---
    restored_sandbox_2 = FakeSandbox(sandbox_id)
    mock_create_instance.return_value = restored_sandbox_2
    sandbox_2 = await mgr.restore_sandbox(sandbox_id)
    assert sandbox_2 is restored_sandbox_2
    assert mgr.get_sandbox(sandbox_id) is restored_sandbox_2

# --- Filesystem Snapshot Tests ---

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_create_with_filesystem_snapshot(mock_create_instance, tmp_path):
    """
    Tests that creating a sandbox with a filesystem snapshot sets the correct config.
    """
    # Arrange
    sandbox = FakeSandbox("snapshot-sandbox")
    mock_create_instance.return_value = sandbox
    mgr = SandboxManager()
    mgr.gcs_config = GCSConfig(filesystem_snapshot_mount_path=str(tmp_path))
    
    # Act
    await mgr.create_sandbox(sandbox_id="snapshot-sandbox", filesystem_snapshot_name="my-snapshot.tar")
    
    # Assert
    _, kwargs = mock_create_instance.call_args
    config = kwargs["config"]
    assert config.filesystem_snapshot_path == str(tmp_path / "my-snapshot.tar")

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_create_with_filesystem_snapshot_fails_if_not_configured(mock_create_instance):
    """
    Tests that creating a sandbox with a filesystem snapshot fails if the manager
    is not configured with a snapshot path.
    """
    mgr = SandboxManager() # No filesystem_snapshot_path
    with pytest.raises(SandboxCreationError, match="Filesystem snapshot is not enabled on the server."):
        await mgr.create_sandbox(sandbox_id="test", filesystem_snapshot_name="my-snapshot.tar")

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_snapshot_filesystem(mock_create_instance, tmp_path):
    """
    Tests that snapshotting a sandbox's filesystem calls the instance's method.
    """
    # Arrange
    sandbox = FakeSandbox("snapshot-sandbox")
    mock_create_instance.return_value = sandbox
    mgr = SandboxManager()
    mgr.gcs_config = GCSConfig(filesystem_snapshot_mount_path=str(tmp_path))
    await mgr.create_sandbox(sandbox_id="snapshot-sandbox")
    snapshot_path = tmp_path / "my-snapshot.tar"
        
    # Act
    await mgr.snapshot_filesystem("snapshot-sandbox", "my-snapshot.tar")
        
    # Assert
    assert snapshot_path.is_file()

@patch('src.sandbox.factory.create_sandbox_instance')
async def test_snapshot_filesystem_fails(mock_create_instance, tmp_path):
    """
    Tests that the manager correctly handles a failure during snapshotting.
    """
    # Arrange
    config = FakeSandboxConfig(snapshot_filesystem_should_fail=True)
    sandbox = FakeSandbox("fail-snapshot-sandbox", config=config)
    mock_create_instance.return_value = sandbox
    mgr = SandboxManager()
    mgr.gcs_config = GCSConfig(filesystem_snapshot_mount_path=str(tmp_path))
    await mgr.create_sandbox(sandbox_id="fail-snapshot-sandbox")
    
    # Act & Assert
    with pytest.raises(SandboxSnapshotFilesystemError, match="Fake sandbox failed to snapshot filesystem as configured."):
        await mgr.snapshot_filesystem("fail-snapshot-sandbox", "my-snapshot.tar")

