from .interface import SandboxInterface

class GVisorSandbox(SandboxInterface):
    """
    The real gVisor sandbox implementation.
    (To be implemented later)
    """
    def __init__(self, sandbox_id):
        self._sandbox_id = sandbox_id

    @property
    def sandbox_id(self):
        raise NotImplementedError

    async def create(self):
        raise NotImplementedError

    async def start(self, code: str):
        raise NotImplementedError

    async def stop(self):
        raise NotImplementedError

    async def delete(self):
        raise NotImplementedError

    async def connect(self):
        # This is a placeholder for the async generator
        if False:
            yield
