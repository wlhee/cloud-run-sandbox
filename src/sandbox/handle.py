from dataclasses import dataclass, field, asdict
from typing import Optional, Callable, Type
import asyncio
import time
import os
import json
import logging

from .config import GCSConfig
from .interface import SandboxCreationError, SandboxRestoreError, SandboxOperationError

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
    # Whether this sandbox supports checkpointing.
    enable_sandbox_checkpoint: bool = False


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
    instance: any
    idle_timeout: int

    # In-memory runtime state
    last_activity: float = field(default_factory=time.time)
    cleanup_task: asyncio.Task = None
    delete_callback: Optional[Callable[[str], None]] = None
    ip_address: Optional[str] = None

    gcs_config: Optional[GCSConfig] = None
    gcs_metadata: Optional[GCSSandboxMetadata] = None

    def __init__(
            self,
            sandbox_id: str,
            instance: any,
            idle_timeout: int,
            gcs_config: Optional[GCSConfig] = None,
            delete_callback: Optional[Callable[[str], None]] = None,
            ip_address: Optional[str] = None,
            **kwargs):
        """
        Basic constructor for a SandboxHandle. Should not be called directly.
        Use the factory methods `create_ephemeral` or `create_persistent` instead.
        """
        self.sandbox_id = sandbox_id
        self.instance = instance
        self.idle_timeout = idle_timeout
        self.gcs_config = gcs_config
        self.delete_callback = delete_callback
        self.ip_address = ip_address
        self.last_activity = time.time()
        self._checkpoint_id: Optional[str] = None

    @classmethod
    def create_ephemeral(
        cls: Type['SandboxHandle'],
        sandbox_id: str,
        instance: any,
        idle_timeout: int,
        gcs_config: Optional[GCSConfig] = None,
        delete_callback: Optional[Callable[[str], None]] = None,
        ip_address: Optional[str] = None,
        **kwargs
    ) -> 'SandboxHandle':
        """
        Factory for creating a basic, temporary, in-memory sandbox handle.

        An ephemeral handle can optionally have a `gcs_config` passed to it.
        This does not make the sandbox persistent, but it allows the handle
        to be aware of GCS mount paths for features like filesystem snapshotting,
        which can be performed on any sandbox.
        """
        return cls(sandbox_id, instance, idle_timeout, gcs_config=gcs_config, delete_callback=delete_callback, ip_address=ip_address, **kwargs)

    @classmethod
    def create_persistent(
        cls: Type['SandboxHandle'],
        sandbox_id: str,
        instance: any,
        idle_timeout: int,
        gcs_config: GCSConfig,
        delete_callback: Optional[Callable[[str], None]] = None,
        ip_address: Optional[str] = None,
        **kwargs
    ) -> 'SandboxHandle':
        """
        Factory method to create a new persistent (checkpointable) sandbox.

        It validates that the server is configured for checkpointing, creates
        the metadata with `enable_sandbox_checkpoint=True`, creates the GCS
        directory, and performs the initial metadata write.
        """
        # 1. Validate Capabilities
        if not gcs_config.metadata_mount_path:
            raise SandboxCreationError("Server is not configured for persistence: SANDBOX_METADATA_MOUNT_PATH is not set.")
        if not gcs_config.metadata_bucket:
            raise SandboxCreationError("Server is not configured for persistence: SANDBOX_METADATA_BUCKET is not set.")
        if not gcs_config.sandbox_checkpoint_mount_path:
            raise SandboxCreationError("Server is not configured for persistence: SANDBOX_CHECKPOINT_MOUNT_PATH is not set.")
        if not gcs_config.sandbox_checkpoint_bucket:
            raise SandboxCreationError("Server is not configured for persistence: SANDBOX_CHECKPOINT_BUCKET is not set.")

        # 2. Instantiate Handle
        handle = cls(sandbox_id, instance, idle_timeout, gcs_config=gcs_config, delete_callback=delete_callback, ip_address=ip_address, **kwargs)

        # 3. Create Metadata Object
        handle.gcs_metadata = GCSSandboxMetadata(
            sandbox_id=sandbox_id,
            created_timestamp=time.time(),
            idle_timeout=idle_timeout,
            enable_sandbox_checkpoint=True,
        )

        # 4. Create Base Directory
        handle._create_new_directory(os.path.dirname(handle.metadata_path))

        # 5. Write Initial Metadata
        handle.write_metadata()

        # 6. Return Handle
        return handle

    @classmethod
    def attach_persistent(
        cls: Type['SandboxHandle'],
        sandbox_id: str,
        instance: any,
        gcs_config: GCSConfig,
        delete_callback: Optional[Callable[[str], None]] = None,
        ip_address: Optional[str] = None,
        **kwargs
    ) -> 'SandboxHandle':
        """
        Factory method to create a SandboxHandle for an *existing* persistent sandbox
        by loading its metadata from GCS. This is the "attach/restore path".

        It reads the metadata.json, validates its contents against the current
        server configuration, and returns a fully initialized handle.
        """
        metadata_path = os.path.join(gcs_config.metadata_mount_path, "sandboxes", sandbox_id, "metadata.json")
        
        try:
            with open(metadata_path, "r") as f:
                data = json.load(f)
            
            checkpoint_data = data.get("latest_sandbox_checkpoint")
            if checkpoint_data:
                data["latest_sandbox_checkpoint"] = GCSArtifact(**checkpoint_data)

            metadata = GCSSandboxMetadata(**data)
        except FileNotFoundError:
            raise SandboxRestoreError(f"Metadata file not found for sandbox {sandbox_id} at {metadata_path}")
        except (json.JSONDecodeError, TypeError) as e:
            raise SandboxRestoreError(f"Failed to parse or validate metadata for sandbox {sandbox_id}: {e}")

        # --- Validation ---
        if metadata.enable_sandbox_checkpoint and not gcs_config.sandbox_checkpoint_mount_path:
            raise SandboxRestoreError(f"Cannot attach to sandbox {sandbox_id}: it requires checkpointing, but the server is not configured for it.")
        
        if metadata.latest_sandbox_checkpoint:
            checkpoint = metadata.latest_sandbox_checkpoint
            if checkpoint.bucket != gcs_config.sandbox_checkpoint_bucket:
                raise SandboxRestoreError(
                    f"Mismatched checkpoint bucket for {sandbox_id}: "
                    f"metadata has '{checkpoint.bucket}', but server is configured for '{gcs_config.sandbox_checkpoint_bucket}'."
                )

        # Use the idle_timeout from the authoritative metadata file
        handle = cls(
            sandbox_id=sandbox_id,
            instance=instance,
            idle_timeout=metadata.idle_timeout,
            gcs_config=gcs_config,
            delete_callback=delete_callback,
            ip_address=ip_address,
            **kwargs
        )
        # Overwrite the gcs_metadata that the constructor might have created
        handle.gcs_metadata = metadata
        return handle

    def _create_new_directory(self, dir_path: Optional[str]):
        """Helper to create a new directory, failing if it already exists."""
        if dir_path:
            try:
                os.makedirs(dir_path, exist_ok=False)
            except OSError as e:
                # Re-raise as a more specific exception if it's a FileExistsError
                if os.path.exists(dir_path):
                    raise SandboxCreationError(f"Sandbox directory already exists at {dir_path}")
                raise SandboxCreationError(f"Failed to create directory at {dir_path}: {e}")

    def _ensure_directory_exists(self, dir_path: Optional[str]):
        """Helper to ensure a directory exists, creating it if it doesn't."""
        if dir_path:
            try:
                os.makedirs(dir_path, exist_ok=True)
            except OSError as e:
                raise SandboxCreationError(f"Failed to create directory at {dir_path}: {e}")

    def write_metadata(self):
        """Serializes and writes the current gcs_metadata to metadata.json."""
        if not self.gcs_metadata or not self.metadata_path:
            return

        try:
            with open(self.metadata_path, "w") as f:
                json.dump(asdict(self.gcs_metadata), f, indent=2)
        except (IOError, TypeError) as e:
            raise SandboxOperationError(f"Failed to write metadata for sandbox {self.sandbox_id}: {e}")

    @property
    def is_sandbox_checkpointable(self) -> bool:
        """Checks if the sandbox is configured to allow checkpointing."""
        return self.gcs_metadata is not None and self.gcs_metadata.enable_sandbox_checkpoint

    def update_latest_checkpoint(self):
        """
        Updates the metadata with the new latest checkpoint and persists it.
        Uses the internally generated checkpoint ID.
        """
        if not self.gcs_metadata or not self.gcs_config:
            raise SandboxOperationError("Cannot update checkpoint for a non-persistent handle.")
        if self._checkpoint_id is None:
            raise SandboxOperationError("A checkpoint ID has not been generated for this handle yet.")

        # Construct the relative path for the artifact
        relative_path = os.path.join("sandbox_checkpoints", self._checkpoint_id)
        
        self.gcs_metadata.latest_sandbox_checkpoint = GCSArtifact(
            bucket=self.gcs_config.sandbox_checkpoint_bucket,
            path=relative_path,
        )
        self.write_metadata()

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

    def sandbox_checkpoint_dir_path(self) -> Optional[str]:
        """
        Constructs the full local path for a new sandbox checkpoint directory.
        A unique ID is generated and memoized on the first call.
        Ensures the directory exists before returning.
        """
        if not (self.gcs_config and self.gcs_config.sandbox_checkpoint_mount_path):
            return None
        
        if self._checkpoint_id is None:
            self._checkpoint_id = f"ckpt_{time.time_ns()}"
        
        path = os.path.join(self.gcs_config.sandbox_checkpoint_mount_path, "sandbox_checkpoints", self._checkpoint_id)
        self._ensure_directory_exists(path)
        return path

    @classmethod
    def build_filesystem_snapshot_path(cls, gcs_config: GCSConfig, sandbox_id: str, snapshot_name: str) -> Optional[str]:
        """
        Constructs the full local path for a new filesystem snapshot file.
        """
        if not gcs_config or not gcs_config.filesystem_snapshot_mount_path:
            return None
        return os.path.join(gcs_config.filesystem_snapshot_mount_path, "filesystem_snapshots", sandbox_id, f"{snapshot_name}.tar")

    def filesystem_snapshot_file_path(self, snapshot_id: str, create_parent_dir: bool = False) -> Optional[str]:
        """
        Constructs the full local path for a new filesystem snapshot file.

        Note: This method is available on all handles (ephemeral or persistent)
        that have a gcs_config. The SandboxManager is responsible for checking
        *if* the server has snapshotting enabled before calling this method.
        This method is only responsible for knowing *where* the snapshot should go.
        """
        path = self.build_filesystem_snapshot_path(self.gcs_config, snapshot_id, snapshot_id)
        if not path:
            return None
        if create_parent_dir:
            self._ensure_directory_exists(os.path.dirname(path))
        return path

    @property
    def latest_checkpoint_path(self) -> Optional[str]:
        """
        Constructs the full local path to the latest checkpoint image.
        Assumes metadata has been validated on load.
        """
        if not self.gcs_metadata or not self.gcs_metadata.latest_sandbox_checkpoint:
            return None
        
        checkpoint = self.gcs_metadata.latest_sandbox_checkpoint
        config = self.gcs_config

        if config and config.sandbox_checkpoint_mount_path:
            return os.path.join(config.sandbox_checkpoint_mount_path, checkpoint.path)
        
        return None
