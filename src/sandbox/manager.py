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
from .interface import SandboxCreationError, SandboxOperationError, SandboxRestoreError, SandboxSnapshotFilesystemError, SandboxExecutionInProgressError, SandboxCheckpointError, SandboxNotFoundError, StatusNotifier
from .lock.factory import LockFactory
from .types import SandboxStateEvent

logger = logging.getLogger(__name__)

class SandboxManager:
    """
    Manages the lifecycle of stateful sandbox instances.
    """
    def __init__(self, gcs_config: Optional[GCSConfig] = None, lock_factory: Optional[LockFactory] = None):
        self._sandboxes: dict[str, SandboxHandle] = {}
        self._ip_pool = {f"192.168.100.{i}" for i in range(2, 255)}
        self._ip_allocations: dict[str, str] = {}
        self.gcs_config = gcs_config
        self.lock_factory = lock_factory
        self._cleanup_task: Optional[asyncio.Task] = None

    def enable_idle_cleanup(self, cleanup_interval: int = 10):
        """Starts the background task that cleans up idle sandboxes."""
        if self._cleanup_task is None:
            self._cleanup_interval = cleanup_interval
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        """A background task that periodically cleans up idle sandboxes."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                for sandbox_id in list(self._sandboxes.keys()):
                    handle = self._sandboxes.get(sandbox_id)
                    if not handle or not handle.idle_timeout:
                        continue

                    is_expired = time.time() - handle.last_activity > handle.idle_timeout
                    if is_expired and not handle.instance.is_execution_running:
                        logger.info(f"Sandbox {sandbox_id} has been idle for {handle.idle_timeout} seconds. Deleting.")
                        await self.delete_sandbox(sandbox_id)
            except asyncio.CancelledError:
                logger.info("Sandbox cleanup loop cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in sandbox cleanup loop: {e}")


    @property
    def is_sandbox_checkpointing_enabled(self) -> bool:
        """Checks if sandbox checkpointing is fully configured."""
        return (
            self.gcs_config is not None and
            self.gcs_config.metadata_mount_path is not None and
            self.gcs_config.metadata_bucket is not None and
            self.gcs_config.sandbox_checkpoint_mount_path is not None and
            self.gcs_config.sandbox_checkpoint_bucket is not None
        )

    @property
    def is_filesystem_snapshotting_enabled(self) -> bool:
        """Checks if filesystem snapshotting is fully configured."""
        return (
            self.gcs_config is not None and
            self.gcs_config.filesystem_snapshot_mount_path is not None and
            self.gcs_config.filesystem_snapshot_bucket is not None
        )

    async def create_sandbox(
        self,
        sandbox_id: str = None,
        idle_timeout: int = None,
        delete_callback: Optional[Callable[[str], None]] = None,
        enable_checkpoint: bool = False,
        filesystem_snapshot_name: str = None,
        enable_sandbox_handoff: bool = False,
        status_notifier: Optional[StatusNotifier] = None,
    ):
        """
        Creates and initializes a new sandbox instance using the factory.
        If idle_timeout is provided, the sandbox will be automatically
        deleted after that many seconds of inactivity.
        A callback can be provided which will be invoked upon deletion.
        """
        if sandbox_id is None:
            sandbox_id = "sandbox-" + str(uuid.uuid4())[:4]

        if enable_sandbox_handoff and not enable_checkpoint:
            raise SandboxCreationError("Sandbox handoff requires checkpointing to be enabled.")

        config = factory.make_sandbox_config()
        ip_address = None
        handle = None
        success = False

        try:
            if filesystem_snapshot_name:
                if not self.is_filesystem_snapshotting_enabled:
                    raise SandboxCreationError("Filesystem snapshot is not enabled on the server.")
                
                config.filesystem_snapshot_path = SandboxHandle.build_filesystem_snapshot_path(
                    self.gcs_config, filesystem_snapshot_name
                )

            if enable_checkpoint:
                if not self.is_sandbox_checkpointing_enabled:
                    raise SandboxCreationError("Checkpointing is not enabled on the server.")
                config.network = "sandbox"
                config.checkpointable = True

            if config.network == "sandbox":
                if not self._ip_pool:
                    raise SandboxCreationError("No available IP addresses in the pool.")
                ip_address = self._ip_pool.pop()
                self._ip_allocations[sandbox_id] = ip_address
                config.ip_address = ip_address

            if enable_checkpoint:
                handle = await SandboxHandle.create_persistent(
                    sandbox_id=sandbox_id,
                    instance=None, # Instance created later
                    idle_timeout=idle_timeout,
                    gcs_config=self.gcs_config,
                    lock_factory=self.lock_factory,
                    delete_callback=delete_callback,
                    ip_address=ip_address,
                    enable_sandbox_handoff=enable_sandbox_handoff,
                    on_release_requested=self._on_release_requested,
                    on_renewal_error=self._on_renewal_error,
                    status_notifier=status_notifier,
                )
            else:
                handle = SandboxHandle.create_ephemeral(
                    sandbox_id=sandbox_id,
                    instance=None, # Instance created later
                    idle_timeout=idle_timeout,
                    gcs_config=self.gcs_config,
                    delete_callback=delete_callback,
                    ip_address=ip_address,
                )

            sandbox_instance = factory.create_sandbox_instance(sandbox_id, config=config)
            await sandbox_instance.create()
            handle.instance = sandbox_instance

            self._sandboxes[sandbox_id] = handle
            logger.info(f"Sandbox manager created {sandbox_id}. Current sandboxes: {list(self._sandboxes.keys())}")
            success = True
            return sandbox_instance
        finally:
            if not success:
                if ip_address:
                    self._ip_pool.add(ip_address)
                    del self._ip_allocations[sandbox_id]
                if handle and handle.lock:
                    if handle.status_notifier:
                        await handle.status_notifier.send_status(SandboxStateEvent.SANDBOX_LOCK_RELEASING)
                    await handle.lock.release()
                    if handle.status_notifier:
                        await handle.status_notifier.send_status(SandboxStateEvent.SANDBOX_LOCK_RELEASED)

    def get_sandbox(self, sandbox_id):
        """
        Retrieves a sandbox instance by its ID. This is the public-facing
        method and should be used by API layers. It implicitly resets the
        idle timer.
        """
        handle = self._sandboxes.get(sandbox_id)
        if handle:
            self.reset_idle_timer(sandbox_id)
            return handle.instance
        return None

    async def restore_sandbox(
            self,
            sandbox_id: str,
            delete_callback: Optional[Callable[[str], None]] = None,
            status_notifier: Optional[StatusNotifier] = None,
        ):
        """
        Restores a sandbox from its checkpoint on the persistence volume.
        Returns None if no checkpoint is found.
        """
        if self.get_sandbox(sandbox_id):
            raise SandboxOperationError(f"Sandbox {sandbox_id} is already in memory.")

        if not self.is_sandbox_checkpointing_enabled:
            return None
        
        handle = None
        ip_address = None
        success = False
        try:
            handle = await SandboxHandle.attach_persistent(
                sandbox_id=sandbox_id,
                instance=None, # Instance created later
                gcs_config=self.gcs_config,
                lock_factory=self.lock_factory,
                delete_callback=delete_callback,
                on_release_requested=self._on_release_requested,
                on_renewal_error=self._on_renewal_error,
                status_notifier=status_notifier,
            )

            config = factory.make_sandbox_config()
            config.network = "sandbox"
            config.checkpointable = True
            
            if not self._ip_pool:
                raise SandboxCreationError("No available IP addresses in the pool.")
            ip_address = self._ip_pool.pop()
            self._ip_allocations[sandbox_id] = ip_address
            config.ip_address = ip_address
            handle.ip_address = ip_address

            sandbox_instance = factory.create_sandbox_instance(sandbox_id, config=config)
            handle.instance = sandbox_instance
            
            checkpoint_path = handle.latest_checkpoint_path
            if not checkpoint_path or not os.path.exists(checkpoint_path):
                raise SandboxRestoreError(f"Latest checkpoint not found for sandbox {sandbox_id}")
            logger.info(f"Restoring sandbox {sandbox_id} from {checkpoint_path}")
            
            try:
                await sandbox_instance.restore(checkpoint_path)
            except SandboxOperationError as e:
                logger.error(f"Failed to restore sandbox {sandbox_id}: {e}")
                raise SandboxRestoreError(f"Failed to restore sandbox {sandbox_id}") from e

            self._sandboxes[sandbox_id] = handle
            success = True
            return sandbox_instance
        except SandboxNotFoundError:
            return None
        finally:
            if not success:
                if ip_address:
                    self._ip_pool.add(ip_address)
                    del self._ip_allocations[sandbox_id]
                if handle and handle.lock:
                    await handle.lock.release()

    def reset_idle_timer(self, sandbox_id: str):
        """
        Updates the last activity time for a sandbox.
        """
        handle = self._sandboxes.get(sandbox_id)
        if handle and handle.idle_timeout:
            logger.debug(f"Updating activity for sandbox {sandbox_id}")
            handle.last_activity = time.time()

    async def checkpoint_sandbox(self, sandbox_id: str, force: bool = False):
        """
        Checkpoints a sandbox and then removes it from the local manager.
        """
        handle = self._sandboxes.get(sandbox_id)
        if not handle:
            raise SandboxOperationError(f"Sandbox not found: {sandbox_id}")

        if not handle.is_sandbox_checkpointable:
            raise SandboxOperationError(f"Sandbox {sandbox_id} is not configured for checkpointing.")

        try:
            checkpoint_path = handle.sandbox_checkpoint_dir_path()
            await handle.instance.checkpoint(checkpoint_path, force=force)

            # Verify that the checkpoint has been fully persisted to GCS.
            await handle.verify_checkpoint_persisted()

            # The handle is now responsible for updating its own metadata
            handle.update_latest_checkpoint()
            logger.info(f"Sandbox {sandbox_id} checkpointed to {checkpoint_path}")
            # After checkpointing, the local instance is no longer valid.
            await self.delete_sandbox(sandbox_id)
        except SandboxExecutionInProgressError:
            # Re-raise the specific error to be handled by the caller (websocket handler)
            raise
        except Exception as e:
            # On other errors, delete the sandbox to ensure a clean state
            await self.delete_sandbox(sandbox_id)
            raise SandboxCheckpointError(f"Failed to checkpoint sandbox {sandbox_id}: {e}") from e

    async def snapshot_filesystem(self, sandbox_id: str, snapshot_name: str):
        """
        Snapshots the filesystem of a sandbox.
        """
        if not self.is_filesystem_snapshotting_enabled:
            raise SandboxOperationError("Filesystem snapshot is not enabled on the server.")

        handle = self._sandboxes.get(sandbox_id)
        if not handle:
            raise SandboxOperationError(f"Sandbox not found: {sandbox_id}")

        snapshot_path = handle.filesystem_snapshot_file_path(snapshot_name, create_parent_dir=True)
        await handle.instance.snapshot_filesystem(snapshot_path)
        logger.info(f"Sandbox {sandbox_id} filesystem snapshotted to {snapshot_path}")

    async def delete_sandbox(self, sandbox_id: str):
        """
        Deletes a sandbox and removes it from the manager.
        """
        logger.info(f"Sandbox manager deleting sandbox {sandbox_id}...")
        handle = self._sandboxes.pop(sandbox_id, None)
        if handle:
            if handle.status_notifier:
                await handle.status_notifier.send_status(SandboxStateEvent.SANDBOX_DELETING)
            await handle.instance.delete()
            
            if handle.lock:
                await handle.lock.release()

            # Release the IP address back to the pool.
            if handle.ip_address:
                self._ip_pool.add(handle.ip_address)
                del self._ip_allocations[sandbox_id]

            if handle.delete_callback:
                handle.delete_callback(sandbox_id)
            
            if handle.status_notifier:
                await handle.status_notifier.send_status(SandboxStateEvent.SANDBOX_DELETED)

            logger.info(f"Sandbox manager deleted {sandbox_id}. Current sandboxes: {list(self._sandboxes.keys())}")

    async def delete_all_sandboxes(self):
        """
        Deletes all sandboxes managed by this instance and stops the cleanup loop.
        """
        logger.info("Stopping sandbox cleanup loop...")
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                logger.info("Sandbox cleanup loop stopped successfully.")

        logger.info("Deleting all sandboxes...")
        
        # For integration testing: create a file to signal that this was called.
        shutdown_test_file = os.environ.get("SHUTDOWN_TEST_FILE")
        if shutdown_test_file:
            Path(shutdown_test_file).touch()

        sandbox_ids = list(self._sandboxes.keys())
        for sandbox_id in sandbox_ids:
            await self.delete_sandbox(sandbox_id)
        logger.info("All sandboxes deleted.")

    async def _on_release_requested(self, sandbox_id: str):
        """Callback for when another process wants to take over the sandbox."""
        logger.warning(f"Lock release requested for sandbox {sandbox_id}. Checkpointing and shutting down.")
        handle = self._sandboxes.get(sandbox_id)
        if handle and handle.status_notifier:
            await handle.status_notifier.send_status(SandboxStateEvent.SANDBOX_LOCK_RELEASE_REQUESTED) 
            await handle.status_notifier.send_status(SandboxStateEvent.SANDBOX_CHECKPOINTING)
        try:
            await self.checkpoint_sandbox(sandbox_id, force=True)
        except Exception as e:
            if handle and handle.status_notifier:
                await handle.status_notifier.send_status(SandboxStateEvent.SANDBOX_CHECKPOINT_ERROR)
            raise
        finally:
            if handle and handle.status_notifier:
                await handle.status_notifier.send_status(SandboxStateEvent.SANDBOX_CHECKPOINTED)

    async def _on_renewal_error(self, sandbox_id: str):
        """Callback for when the lock renewal fails."""
        logger.error(f"Lock renewal failed for sandbox {sandbox_id}. Shutting down.")
        handle = self._sandboxes.get(sandbox_id)
        if handle and handle.status_notifier:
            await handle.status_notifier.send_status(SandboxStateEvent.SANDBOX_LOCK_RENEWAL_ERROR)
        await self.delete_sandbox(sandbox_id)

# Create a placeholder for the single, global instance of the manager.
# This will be replaced by a properly configured instance at startup.
manager: Optional["SandboxManager"] = None