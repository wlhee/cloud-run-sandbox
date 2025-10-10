from dataclasses import dataclass, field
from typing import Optional, Callable
import asyncio
import time
import os
import logging

from .config import GCSConfig

logger = logging.getLogger(__name__)


@dataclass
class GCSArtifact:
    """
    Represents a generic artifact stored in GCS.
    """
    # The GCS bucket name. Example: "my-sandbox-artifacts"
    bucket: str
    # The path to the artifact within the bucket. Example: "sandbox_checkpoints/ckpt-xyz/"
    path: str


@dataclass
class GCSSandboxMetadata:
    """
    Represents the structure of the metadata.json file in GCS. This is the persistent state.
    """
    # The unique ID of the sandbox. Example: "sandbox-abc-123"
    sandbox_id: str
    # Unix timestamp (seconds since epoch) of when the sandbox was created.
    created_timestamp: float
    # The idle timeout in seconds. Example: 300
    idle_timeout: Optional[int] = None
    # A GCSArtifact pointing to the latest checkpoint.
    latest_sandbox_checkpoint: Optional[GCSArtifact] = None


@dataclass
class SandboxHandle:
    """
    A centralized class to manage all state and configuration for a single sandbox instance.
    It holds both in-memory runtime data (like the instance and cleanup tasks) and,
    optionally, the GCS persistence configuration and loaded metadata.

    This class is also the single source of truth for constructing GCS paths,
    ensuring consistency and making path logic easily testable.
    """
    sandbox_id: str
    gcs_config: Optional[GCSConfig] = None
    gcs_metadata: Optional[GCSSandboxMetadata] = None

    # In-memory runtime state
    instance: any = None
    idle_timeout: Optional[int] = None
    last_activity: float = field(default_factory=time.time)
    cleanup_task: asyncio.Task = None
    delete_callback: Optional[Callable[[str], None]] = None
    ip_address: Optional[str] = None

    @property
    def is_persistent(self) -> bool:
        """Checks if the sandbox has GCS metadata associated with it."""
        return self.gcs_metadata is not None

    @property
    def metadata_path(self) -> Optional[str]:
        """Constructs the full local path to the metadata.json file."""
        if self.gcs_config and self.gcs_config.metadata_mount_path:
            return os.path.join(self.gcs_config.metadata_mount_path, "sandboxes", self.sandbox_id, "metadata.json")
        return None

    @property
    def lock_path(self) -> Optional[str]:
        """Constructs the full local path to the lock.json file."""
        if self.gcs_config and self.gcs_config.metadata_mount_path:
            return os.path.join(self.gcs_config.metadata_mount_path, "sandboxes", self.sandbox_id, "lock.json")
        return None

    @property
    def checkpoints_dir(self) -> Optional[str]:
        """Constructs the full local path to the global directory where new checkpoints are stored."""
        if self.gcs_config and self.gcs_config.sandbox_checkpoint_mount_path:
            return os.path.join(self.gcs_config.sandbox_checkpoint_mount_path, "sandbox_checkpoints")
        return None

    @property
    def latest_checkpoint_path(self) -> Optional[str]:
        """
        Constructs the full local path to the latest checkpoint image, performing
        a sanity check against the server's configuration.
        """
        if not self.gcs_metadata or not self.gcs_metadata.latest_sandbox_checkpoint:
            return None
        
        checkpoint = self.gcs_metadata.latest_sandbox_checkpoint
        config = self.gcs_config

        # Sanity check: Ensure the bucket in the metadata matches the server's config.
        if not config or checkpoint.bucket != config.sandbox_checkpoint_bucket:
            logger.warning(
                f"Mismatched checkpoint bucket for {self.sandbox_id}: "
                f"metadata has '{checkpoint.bucket}', server is configured for '{config.sandbox_checkpoint_bucket}'."
            )
            return None

        if config.sandbox_checkpoint_mount_path:
            # The path in the artifact is relative to the bucket root, so we join it
            # with the local mount path for that bucket.
            return os.path.join(config.sandbox_checkpoint_mount_path, checkpoint.path)
        
        # TODO: Add support for non-mounted GCS client access
        return None
