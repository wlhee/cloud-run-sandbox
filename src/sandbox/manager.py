import uuid
import logging
from . import factory
import asyncio
from dataclasses import dataclass, field
import time
from typing import Callable, Optional
import os
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class SandboxMetadata:
    instance: any
    idle_timeout: int = None
    last_activity: float = field(default_factory=time.time)
    cleanup_task: asyncio.Task = None
    delete_callback: Optional[Callable[[str], None]] = None

class SandboxManager:
    """
    Manages the lifecycle of stateful sandbox instances.
    """
    def __init__(self):
        self._sandboxes: dict[str, SandboxMetadata] = {}

    async def create_sandbox(
        self,
        sandbox_id: str = None,
        idle_timeout: int = None,
        delete_callback: Optional[Callable[[str], None]] = None
    ):
        """
        Creates and initializes a new sandbox instance using the factory.
        If idle_timeout is provided, the sandbox will be automatically
        deleted after that many seconds of inactivity.
        A callback can be provided which will be invoked upon deletion.
        """
        if sandbox_id is None:
            sandbox_id = "sandbox-" + str(uuid.uuid4())[:4]
        
        sandbox_instance = factory.create_sandbox_instance(sandbox_id)
        
        await sandbox_instance.create()

        metadata = SandboxMetadata(
            instance=sandbox_instance,
            idle_timeout=idle_timeout,
            delete_callback=delete_callback,
        )

        if idle_timeout:
            metadata.cleanup_task = asyncio.create_task(self._idle_cleanup(sandbox_id, idle_timeout))

        self._sandboxes[sandbox_id] = metadata
        logger.info(f"Sandbox manager created {sandbox_id}. Current sandboxes: {list(self._sandboxes.keys())}")
        return sandbox_instance

    def get_sandbox(self, sandbox_id):
        """Retrieves a sandbox by its ID and updates its activity."""
        metadata = self._sandboxes.get(sandbox_id)
        if metadata:
            self.update_sandbox_activity(sandbox_id)
            return metadata.instance
        return None

    def update_sandbox_activity(self, sandbox_id: str):
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
