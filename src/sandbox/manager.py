import uuid
from .sandbox import FakeSandbox, GVisorSandbox

class SandboxManager:
    """
    Manages the lifecycle of all sandbox instances.
    """
    def __init__(self):
        self._sandboxes = {}

    def create_sandbox(self, sandbox_id=None, use_fake=True):
        """
        Creates a new sandbox instance and adds it to the manager.
        """
        if sandbox_id is None:
            sandbox_id = "sandbox-" + str(uuid.uuid4())[:4]
        
        if use_fake:
            sandbox = FakeSandbox(sandbox_id)
        else:
            sandbox = GVisorSandbox(sandbox_id)
            
        self._sandboxes[sandbox_id] = sandbox
        print(f"Sandbox manager created {sandbox_id}. Current sandboxes: {list(self._sandboxes.keys())}")
        return sandbox

    def get_sandbox(self, sandbox_id):
        """Retrieves a sandbox by its ID."""
        return self._sandboxes.get(sandbox_id)

    def delete_sandbox(self, sandbox_id):
        """Deletes a sandbox from the manager."""
        if sandbox_id in self._sandboxes:
            del self._sandboxes[sandbox_id]
            print(f"Sandbox manager deleted {sandbox_id}. Current sandboxes: {list(self._sandboxes.keys())}")

# Create a single, global instance of the manager that the application will use.
manager = SandboxManager()