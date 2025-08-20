from .gvisor import GVisorSandbox

def create_sandbox_instance(sandbox_id: str):
    """
    Factory function to create a real GVisorSandbox instance.
    """
    return GVisorSandbox(sandbox_id)
