from dataclasses import dataclass
import os


@dataclass
class GCSConfig:
    """
    Configuration for GCS-backed sandbox persistence and locking.
    """
    metadata_bucket: str | None = None
    metadata_mount_path: str | None = None
    sandbox_checkpoint_bucket: str | None = None
    sandbox_checkpoint_mount_path: str | None = None
    filesystem_snapshot_bucket: str | None = None
    filesystem_snapshot_mount_path: str | None = None

    @classmethod
    def from_env(cls) -> "GCSConfig":
        """
        Creates a GCSConfig instance from environment variables.
        """
        return cls(
            metadata_bucket=os.environ.get("SANDBOX_METADATA_BUCKET"),
            metadata_mount_path=os.environ.get("SANDBOX_METADATA_MOUNT_PATH"),
            sandbox_checkpoint_bucket=os.environ.get("SANDBOX_CHECKPOINT_BUCKET"),
            sandbox_checkpoint_mount_path=os.environ.get("SANDBOX_CHECKPOINT_MOUNT_PATH"),
            filesystem_snapshot_bucket=os.environ.get("FILESYSTEM_SNAPSHOT_BUCKET"),
            filesystem_snapshot_mount_path=os.environ.get("FILESYSTEM_SNAPSHOT_MOUNT_PATH"),
        )

