import uuid
import logging
from . import factory
import asyncio
from dataclasses import dataclass, field
import time
from typing import Callable, Optional
import os
from pathlib import Path
import json

from .handle import SandboxHandle
from .config import GCSConfig
from .interface import SandboxCreationError, SandboxOperationError, SandboxRestoreError, SandboxSnapshotFilesystemError

logger = logging.getLogger(__name__)

class SandboxManager:
    """
    Manages the lifecycle of stateful sandbox instances.
    """
    def __init__(self):
        self._sandboxes: dict[str, SandboxHandle] = {}
        self._ip_pool = {f"192.168.100.{i}" for i in range(2, 255)}
        self._ip_allocations: dict[str, str] = {}
        self.gcs_config: Optional[GCSConfig] = None

    @property
    def is_sandbox_checkpointing_enabled(self) -> bool:
        """Checks if sandbox checkpointing is configured."""
        return self.gcs_config and (
            self.gcs_config.sandbox_checkpoint_bucket or self.gcs_config.sandbox_checkpoint_mount_path
        )

    @property
    def is_filesystem_snapshotting_enabled(self) -> bool:
        """Checks if filesystem snapshotting is configured."""
        return self.gcs_config and (
            self.gcs_config.filesystem_snapshot_bucket or self.gcs_config.filesystem_snapshot_mount_path
        )

    def _read_persistent_metadata(self, sandbox_id: str) -> Optional[dict]:
        """Reads and parses the metadata JSON file for a sandbox."""
        if not self.is_sandbox_checkpointing_enabled:
            return None

        # TODO: This only handles the local mount path case. GCS client logic will be added later.
        base_path = self.gcs_config.sandbox_checkpoint_mount_path
        if not base_path:
            return None

        metadata_path = os.path.join(base_path, sandbox_id, "metadata.json")
        if not os.path.exists(metadata_path):
            return None

        with open(metadata_path, "r") as f:
            return json.load(f)

    def _write_persistent_metadata(self, sandbox_id: str, idle_timeout: int = None):
        """Writes metadata to a JSON file in the sandbox's persistence directory."""
        if not self.is_sandbox_checkpointing_enabled:
            return

        # TODO: This only handles the local mount path case. GCS client logic will be added later.
        base_path = self.gcs_config.sandbox_checkpoint_mount_path
        if not base_path:
            return

        metadata_path = os.path.join(base_path, sandbox_id, "metadata.json")
        
        # When updating, preserve the original idle_timeout if not provided.
        if os.path.exists(metadata_path):
            with open(metadata_path, "r") as f:
                existing_metadata = json.load(f)
            if idle_timeout is None:
                idle_timeout = existing_metadata.get("idle_timeout")

        metadata = {
            "timestamp": time.time(),
            "idle_timeout": idle_timeout,
        }
        
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

    async def create_sandbox(
        self,
        sandbox_id: str = None,
        idle_timeout: int = None,
        delete_callback: Optional[Callable[[str], None]] = None,
        enable_checkpoint: bool = False,
        filesystem_snapshot_name: str = None,
    ):
        """
        Creates and initializes a new sandbox instance using the factory.
        If idle_timeout is provided, the sandbox will be automatically
        deleted after that many seconds of inactivity.
        A callback can be provided which will be invoked upon deletion.
        """
        if sandbox_id is None:
            sandbox_id = "sandbox-" + str(uuid.uuid4())[:4]
        
        config = factory.make_sandbox_config()
        ip_address = None

        if filesystem_snapshot_name:
            if not self.is_filesystem_snapshotting_enabled:
                raise SandboxCreationError("Filesystem snapshot is not enabled on the server.")
            
            # TODO: This only handles the local mount path case. GCS client logic will be added later.
            base_path = self.gcs_config.filesystem_snapshot_mount_path
            if not base_path:
                raise SandboxCreationError("Filesystem snapshot is enabled but no mount path is configured.")

            config.filesystem_snapshot_path = os.path.join(base_path, filesystem_snapshot_name)

        if enable_checkpoint:
            if not self.is_sandbox_checkpointing_enabled:
                raise SandboxCreationError("Checkpointing is not enabled on the server.")
            
            # Enforce network="sandbox" for checkpointing.  
            config.network = "sandbox"
            
            # Create persistence directory.
            try:
                # TODO: This only handles the local mount path case. GCS client logic will be added later.
                base_path = self.gcs_config.sandbox_checkpoint_mount_path
                if not base_path:
                    raise SandboxCreationError("Checkpointing is enabled but no mount path is configured.")

                sandbox_dir = os.path.join(base_path, sandbox_id)
                checkpoints_dir = os.path.join(sandbox_dir, "checkpoints")
                os.makedirs(checkpoints_dir, exist_ok=False)
                self._write_persistent_metadata(sandbox_id, idle_timeout=idle_timeout)
            except FileExistsError:
                raise SandboxCreationError(f"Sandbox directory already exists: {sandbox_dir}")
            except Exception as e:
                raise SandboxCreationError(f"Failed to create sandbox directory: {e}")

        # Allocate an IP address if networking is enabled.
        if config.network == "sandbox":
            if not self._ip_pool:
                raise SandboxCreationError("No available IP addresses in the pool.")
            ip_address = self._ip_pool.pop()
            self._ip_allocations[sandbox_id] = ip_address
            config.ip_address = ip_address

        sandbox_instance = factory.create_sandbox_instance(sandbox_id, config=config)
        
        await sandbox_instance.create()

        handle = SandboxHandle(
            sandbox_id=sandbox_id,
            instance=sandbox_instance,
            idle_timeout=idle_timeout,
            delete_callback=delete_callback,
            ip_address=ip_address,
        )

        if idle_timeout:
            handle.cleanup_task = asyncio.create_task(self._idle_cleanup(sandbox_id, idle_timeout))

        self._sandboxes[sandbox_id] = handle
        logger.info(f"Sandbox manager created {sandbox_id}. Current sandboxes: {list(self._sandboxes.keys())}")
        return sandbox_instance

    def get_sandbox(self, sandbox_id):
        """Retrieves a sandbox by its ID from the in-memory cache."""
        handle = self._sandboxes.get(sandbox_id)
        if handle:
            self.reset_idle_timer(sandbox_id)
            return handle.instance
        return None

    async def restore_sandbox(self, sandbox_id: str, delete_callback: Optional[Callable[[str], None]] = None):
        """
        Restores a sandbox from its checkpoint on the persistence volume.
        """
        if self.get_sandbox(sandbox_id):
            raise SandboxOperationError(f"Sandbox {sandbox_id} is already in memory.")

        if not self.is_sandbox_checkpointing_enabled:
            return None

        # TODO: This only handles the local mount path case. GCS client logic will be added later.
        base_path = self.gcs_config.sandbox_checkpoint_mount_path
        if not base_path:
            return None

        sandbox_dir = os.path.join(base_path, sandbox_id)
        checkpoints_dir = os.path.join(sandbox_dir, "checkpoints")
        latest_path = os.path.join(checkpoints_dir, "latest")
        metadata_path = os.path.join(sandbox_dir, "metadata.json")
        checkpoint_path = None

        if os.path.exists(latest_path):
            with open(latest_path, "r") as f:
                latest_checkpoint_name = f.read().strip()
            checkpoint_path = os.path.join(checkpoints_dir, latest_checkpoint_name)

        if not checkpoint_path or not os.path.exists(checkpoint_path):
            return None

        logger.info(f"Restoring sandbox {sandbox_id} from {checkpoint_path}")
        
        config = factory.make_sandbox_config()
        config.network = "sandbox"
        
        if not self._ip_pool:
            raise SandboxCreationError("No available IP addresses in the pool.")
        ip_address = self._ip_pool.pop()
        self._ip_allocations[sandbox_id] = ip_address
        config.ip_address = ip_address

        sandbox_instance = factory.create_sandbox_instance(sandbox_id, config=config)
        try:
            await sandbox_instance.restore(checkpoint_path)
        except SandboxOperationError as e:
            logger.error(f"Failed to restore sandbox {sandbox_id}: {e}")
            raise SandboxRestoreError(f"Failed to restore sandbox {sandbox_id}") from e

        idle_timeout = None
        if os.path.exists(metadata_path):
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
                idle_timeout = metadata.get("idle_timeout")

        handle = SandboxHandle(
            sandbox_id=sandbox_id,
            instance=sandbox_instance,
            idle_timeout=idle_timeout,
            ip_address=ip_address,
            delete_callback=delete_callback,
        )
        if idle_timeout:
            handle.cleanup_task = asyncio.create_task(self._idle_cleanup(sandbox_id, idle_timeout))

        self._sandboxes[sandbox_id] = handle
        return sandbox_instance

    def reset_idle_timer(self, sandbox_id: str):
        """
        Updates the last activity time for a sandbox, resetting its idle timer.
        Returns the cancelled cleanup task.
        """
        handle = self._sandboxes.get(sandbox_id)
        cancelled_task = None
        if handle and handle.idle_timeout:
            logger.debug(f"Updating activity for sandbox {sandbox_id}")
            handle.last_activity = time.time()
            if handle.cleanup_task:
                handle.cleanup_task.cancel()
                cancelled_task = handle.cleanup_task
            handle.cleanup_task = asyncio.create_task(self._idle_cleanup(sandbox_id, handle.idle_timeout))
        return cancelled_task

    async def checkpoint_sandbox(self, sandbox_id: str):
        """
        Checkpoints a sandbox and then removes it from the local manager.
        """
        if not self.is_sandbox_checkpointing_enabled:
            raise SandboxOperationError("Checkpointing is not enabled on the server.")

        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            raise SandboxOperationError(f"Sandbox not found: {sandbox_id}")

        # TODO: This only handles the local mount path case. GCS client logic will be added later.
        base_path = self.gcs_config.sandbox_checkpoint_mount_path
        if not base_path:
            raise SandboxOperationError("Checkpointing is enabled but no mount path is configured.")

        checkpoints_dir = os.path.join(base_path, sandbox_id, "checkpoints")
        # `runsc checkpoint --image-path` asks for a directory to create checkpoint realted files in.
        # Hence, checkpoint_name is a subdirectory under checkpoints_dir.
        checkpoint_name = f"checkpoint_{time.time_ns()}"
        checkpoint_path = os.path.join(checkpoints_dir, checkpoint_name)

        await sandbox.checkpoint(checkpoint_path)

        # Update the 'latest' file to point to the new checkpoint.
        latest_path = os.path.join(checkpoints_dir, "latest")
        with open(latest_path, "w") as f:
            f.write(checkpoint_name)
        
        self._write_persistent_metadata(sandbox_id, idle_timeout=self._sandboxes[sandbox_id].idle_timeout)
        logger.info(f"Sandbox {sandbox_id} checkpointed to {checkpoint_path}")

        # After checkpointing, the local instance is no longer valid.
        await self.delete_sandbox(sandbox_id)

    async def snapshot_filesystem(self, sandbox_id: str, snapshot_name: str):
        """
        Snapshots the filesystem of a sandbox.
        """
        if not self.is_filesystem_snapshotting_enabled:
            raise SandboxOperationError("Filesystem snapshot is not enabled on the server.")

        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            raise SandboxOperationError(f"Sandbox not found: {sandbox_id}")

        # TODO: This only handles the local mount path case. GCS client logic will be added later.
        base_path = self.gcs_config.filesystem_snapshot_mount_path
        if not base_path:
            raise SandboxOperationError("Filesystem snapshot is enabled but no mount path is configured.")

        snapshot_path = os.path.join(base_path, snapshot_name)
        await sandbox.snapshot_filesystem(snapshot_path)
        logger.info(f"Sandbox {sandbox_id} filesystem snapshotted to {snapshot_path}")

    async def _idle_cleanup(self, sandbox_id: str, timeout: int):
        """A background task that waits for a timeout and then deletes the sandbox."""
        try:
            await asyncio.sleep(timeout)
            logger.info(f"Sandbox {sandbox_id} has been idle for {timeout} seconds. Deleting.")
            await self.delete_sandbox(sandbox_id)
        except asyncio.CancelledError:
            logger.debug(f"Idle cleanup task for {sandbox_id} was cancelled.")

    async def delete_sandbox(self, sandbox_id: str):
        """Deletes a sandbox and removes it from the manager."""
        logger.info(f"Sandbox manager deleting sandbox {sandbox_id}...")
        handle = self._sandboxes.pop(sandbox_id, None)
        if handle:
            if handle.cleanup_task:
                handle.cleanup_task.cancel()
            await handle.instance.delete()
            
            # Release the IP address back to the pool.
            if handle.ip_address:
                self._ip_pool.add(handle.ip_address)
                del self._ip_allocations[sandbox_id]

            if handle.delete_callback:
                handle.delete_callback(sandbox_id)

            logger.info(f"Sandbox manager deleted {sandbox_id}. Current sandboxes: {list(self._sandboxes.keys())}")

    async def delete_all_sandboxes(self):
        """Deletes all sandboxes managed by this instance."""
        logger.info("Deleting all sandboxes...")
        
        # For integration testing: create a file to signal that this was called.
        shutdown_test_file = os.environ.get("SHUTDOWN_TEST_FILE")
        if shutdown_test_file:
            Path(shutdown_test_file).touch()

        sandbox_ids = list(self._sandboxes.keys())
        for sandbox_id in sandbox_ids:
            await self.delete_sandbox(sandbox_id)
        logger.info("All sandboxes deleted.")

# Create a single, global instance of the manager that the application will use.
manager = SandboxManager()
