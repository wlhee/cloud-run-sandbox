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
from .interface import SandboxCreationError, SandboxOperationError

logger = logging.getLogger(__name__)

@dataclass
class SandboxMetadata:
    instance: any
    idle_timeout: int = None
    last_activity: float = field(default_factory=time.time)
    cleanup_task: asyncio.Task = None
    delete_callback: Optional[Callable[[str], None]] = None
    ip_address: Optional[str] = None

class SandboxManager:
    """
    Manages the lifecycle of stateful sandbox instances.
    """
    def __init__(self, checkpoint_and_restore_path: str = None):
        self._sandboxes: dict[str, SandboxMetadata] = {}
        self._ip_pool = {f"192.168.100.{i}" for i in range(2, 255)}
        self._ip_allocations: dict[str, str] = {}
        self.checkpoint_and_restore_path = checkpoint_and_restore_path

    @property
    def is_checkpointing_enabled(self) -> bool:
        return self.checkpoint_and_restore_path is not None

    def _read_persistent_metadata(self, sandbox_id: str) -> Optional[dict]:
        """Reads and parses the metadata JSON file for a sandbox."""
        if not self.is_checkpointing_enabled:
            return None

        metadata_path = os.path.join(self.checkpoint_and_restore_path, sandbox_id, "metadata.json")
        if not os.path.exists(metadata_path):
            return None

        with open(metadata_path, "r") as f:
            return json.load(f)

    def _read_persistent_metadata(self, sandbox_id: str) -> Optional[dict]:
        """Reads and parses the metadata JSON file for a sandbox."""
        if not self.is_checkpointing_enabled:
            return None

        metadata_path = os.path.join(self.checkpoint_and_restore_path, sandbox_id, "metadata.json")
        if not os.path.exists(metadata_path):
            return None

        with open(metadata_path, "r") as f:
            return json.load(f)

    def _write_persistent_metadata(self, sandbox_id: str, status: str, idle_timeout: int = None):
        """Writes metadata to a JSON file in the sandbox's persistence directory."""
        if not self.is_checkpointing_enabled:
            return

        metadata_path = os.path.join(self.checkpoint_and_restore_path, sandbox_id, "metadata.json")
        
        # When updating, preserve the original idle_timeout if not provided.
        if status != "created" and os.path.exists(metadata_path):
            with open(metadata_path, "r") as f:
                existing_metadata = json.load(f)
            if idle_timeout is None:
                idle_timeout = existing_metadata.get("idle_timeout")

        metadata = {
            "status": status,
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

        if enable_checkpoint:
            if not self.is_checkpointing_enabled:
                raise SandboxCreationError("Checkpointing is not enabled on the server.")
            
            # Enforce network="sandbox" for checkpointing.  
            config.network = "sandbox"
            
            # Create persistence directory.
            try:
                sandbox_dir = os.path.join(self.checkpoint_and_restore_path, sandbox_id)
                os.makedirs(sandbox_dir, exist_ok=False)
                self._write_persistent_metadata(sandbox_id, "created", idle_timeout=idle_timeout)
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

        sandbox_instance = factory.create_sandbox_instance(sandbox_id, config=config, checkpoint_path=self.checkpoint_and_restore_path)
        
        await sandbox_instance.create()

        metadata = SandboxMetadata(
            instance=sandbox_instance,
            idle_timeout=idle_timeout,
            delete_callback=delete_callback,
            ip_address=ip_address,
        )

        if idle_timeout:
            metadata.cleanup_task = asyncio.create_task(self._idle_cleanup(sandbox_id, idle_timeout))

        self._sandboxes[sandbox_id] = metadata
        logger.info(f"Sandbox manager created {sandbox_id}. Current sandboxes: {list(self._sandboxes.keys())}")
        return sandbox_instance

    def get_sandbox(self, sandbox_id):
        """Retrieves a sandbox by its ID from the in-memory cache."""
        metadata = self._sandboxes.get(sandbox_id)
        if metadata:
            self.reset_idle_timer(sandbox_id)
            return metadata.instance
        return None

    async def restore_sandbox(self, sandbox_id: str, delete_callback: Optional[Callable[[str], None]] = None):
        """
        Restores a sandbox from its checkpoint on the persistence volume.
        """
        if self.get_sandbox(sandbox_id):
            raise SandboxOperationError(f"Sandbox {sandbox_id} is already in memory.")

        if not self.is_checkpointing_enabled:
            return None

        sandbox_dir = os.path.join(self.checkpoint_and_restore_path, sandbox_id)
        checkpoint_path = os.path.join(sandbox_dir, "checkpoint")
        metadata_path = os.path.join(sandbox_dir, "metadata.json")

        if not os.path.exists(checkpoint_path):
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
            return None

        idle_timeout = None
        if os.path.exists(metadata_path):
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
                idle_timeout = metadata.get("idle_timeout")

        metadata = SandboxMetadata(
            instance=sandbox_instance,
            idle_timeout=idle_timeout,
            ip_address=ip_address,
            delete_callback=delete_callback,
        )
        if idle_timeout:
            metadata.cleanup_task = asyncio.create_task(self._idle_cleanup(sandbox_id, idle_timeout))

        self._sandboxes[sandbox_id] = metadata
        return sandbox_instance

    def reset_idle_timer(self, sandbox_id: str):
        """
        Updates the last activity time for a sandbox, resetting its idle timer.
        Returns the cancelled cleanup task.
        """
        metadata = self._sandboxes.get(sandbox_id)
        cancelled_task = None
        if metadata and metadata.idle_timeout:
            logger.debug(f"Updating activity for sandbox {sandbox_id}")
            metadata.last_activity = time.time()
            if metadata.cleanup_task:
                metadata.cleanup_task.cancel()
                cancelled_task = metadata.cleanup_task
            metadata.cleanup_task = asyncio.create_task(self._idle_cleanup(sandbox_id, metadata.idle_timeout))
        return cancelled_task

    async def checkpoint_sandbox(self, sandbox_id: str):
        """
        Checkpoints a sandbox and then removes it from the local manager.
        """
        if not self.is_checkpointing_enabled:
            raise SandboxOperationError("Checkpointing is not enabled on the server.")

        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            raise SandboxOperationError(f"Sandbox not found: {sandbox_id}")

        checkpoint_path = os.path.join(self.checkpoint_and_restore_path, sandbox_id, "checkpoint")
        await sandbox.checkpoint(checkpoint_path)
        
        self._write_persistent_metadata(sandbox_id, "checkpointed", idle_timeout=self._sandboxes[sandbox_id].idle_timeout)
        logger.info(f"Sandbox {sandbox_id} checkpointed to {checkpoint_path}")

        # After checkpointing, the local instance is no longer valid.
        await self.delete_sandbox(sandbox_id)

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
        metadata = self._sandboxes.pop(sandbox_id, None)
        if metadata:
            if metadata.cleanup_task:
                metadata.cleanup_task.cancel()
            await metadata.instance.delete()
            
            # Release the IP address back to the pool.
            if metadata.ip_address:
                self._ip_pool.add(metadata.ip_address)
                del self._ip_allocations[sandbox_id]

            if metadata.delete_callback:
                metadata.delete_callback(sandbox_id)

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
