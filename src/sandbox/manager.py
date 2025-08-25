import uuid
from . import factory

class SandboxManager:
    """
    Manages the lifecycle of stateful sandbox instances.
    """
    def __init__(self):
        self._sandboxes = {}

    async def create_sandbox(self, sandbox_id=None):
        """
        Creates and initializes a new sandbox instance using the factory.
        """
        if sandbox_id is None:
            sandbox_id = "sandbox-" + str(uuid.uuid4())[:4]
        
        sandbox = factory.create_sandbox_instance(sandbox_id)
        
        await sandbox.create()
        self._sandboxes[sandbox_id] = sandbox
        print(f"Sandbox manager created {sandbox_id}. Current sandboxes: {list(self._sandboxes.keys())}")
        return sandbox

    def get_sandbox(self, sandbox_id):
        """Retrieivs a sandbox by its ID."""
        return self._sandboxes.get(sandbox_id)

    async def delete_sandbox(self, sandbox_id: str):
        """Deletes a sandbox and removes it from the manager."""
        print(f"Sandbox manager deleting sandbox {sandbox_id}...")
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox:
            await sandbox.delete()
            del self._sandboxes[sandbox_id]
            print(f"Sandbox manager deleted {sandbox_id}. Current sandboxes: {list(self._sandboxes.keys())}")

# Create a single, global instance of the manager that the application will use.
manager = SandboxManager()
