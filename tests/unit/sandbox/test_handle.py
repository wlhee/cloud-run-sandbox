import pytest
from src.sandbox.handle import SandboxHandle, GCSSandboxMetadata, GCSArtifact
from src.sandbox.config import GCSConfig

def test_sandbox_handle_path_properties():
    """
    Tests that the path properties of the SandboxHandle are constructed correctly.
    """
    gcs_config = GCSConfig(
        metadata_mount_path="/gcs/metadata",
        sandbox_checkpoint_mount_path="/gcs/checkpoints",
    )
    handle = SandboxHandle(sandbox_id="test-sandbox-123", gcs_config=gcs_config)

    assert handle.metadata_path == "/gcs/metadata/sandboxes/test-sandbox-123/metadata.json"
    assert handle.lock_path == "/gcs/metadata/sandboxes/test-sandbox-123/lock.json"
    assert handle.checkpoints_dir == "/gcs/checkpoints/sandbox_checkpoints"

def test_latest_checkpoint_path_construction():
    """
    Tests that the latest_checkpoint_path is constructed correctly from GCS metadata.
    """
    gcs_config = GCSConfig(
        sandbox_checkpoint_bucket="my-checkpoint-bucket",
        sandbox_checkpoint_mount_path="/gcs/checkpoints",
    )
    gcs_metadata = GCSSandboxMetadata(
        sandbox_id="test-sandbox-123",
        created_timestamp=12345.67,
        latest_sandbox_checkpoint=GCSArtifact(
            bucket="my-checkpoint-bucket",
            path="sandbox_checkpoints/ckpt-xyz/",
        )
    )
    handle = SandboxHandle(
        sandbox_id="test-sandbox-123",
        gcs_config=gcs_config,
        gcs_metadata=gcs_metadata,
    )

    expected_path = "/gcs/checkpoints/sandbox_checkpoints/ckpt-xyz/"
    assert handle.latest_checkpoint_path == expected_path

def test_latest_checkpoint_path_returns_none_on_bucket_mismatch():
    """
    Tests that latest_checkpoint_path returns None if the bucket in the
    metadata does not match the server's configuration.
    """
    gcs_config = GCSConfig(
        sandbox_checkpoint_bucket="a-different-bucket", # Mismatch
        sandbox_checkpoint_mount_path="/gcs/checkpoints",
    )
    gcs_metadata = GCSSandboxMetadata(
        sandbox_id="test-sandbox-123",
        created_timestamp=12345.67,
        latest_sandbox_checkpoint=GCSArtifact(
            bucket="my-checkpoint-bucket",
            path="sandbox_checkpoints/ckpt-xyz/",
        )
    )
    handle = SandboxHandle(
        sandbox_id="test-sandbox-123",
        gcs_config=gcs_config,
        gcs_metadata=gcs_metadata,
    )

    assert handle.latest_checkpoint_path is None
