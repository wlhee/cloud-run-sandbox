from abc import ABC, abstractmethod
import json
import asyncio

class SandboxInterface(ABC):
    """Defines the interface for all sandbox implementations."""
    
    @property
    @abstractmethod
    def sandbox_id(self):
        pass

    @abstractmethod
    async def create(self, code: str):
        pass

    @abstractmethod
    async def start(self, websocket):
        pass

    @abstractmethod
    async def stop(self):
        pass

    @abstractmethod
    async def delete(self):
        pass

class FakeSandbox(SandboxInterface):
    """
    A fake, in-memory sandbox for testing and local development.
    """
    def __init__(self, sandbox_id):
        self._sandbox_id = sandbox_id
        self._websocket = None
        self._code = None
        self._task = None
        self.is_running = False

    @property
    def sandbox_id(self):
        return self._sandbox_id

    async def create(self, code: str):
        print(f"Fake sandbox {self.sandbox_id}: CREATING with code.")
        self._code = code
        await asyncio.sleep(0.01) # Simulate I/O
        print(f"Fake sandbox {self.sandbox_id}: CREATED.")

    async def start(self, websocket):
        self._websocket = websocket
        print(f"Fake sandbox {self.sandbox_id}: STARTING.")
        self.is_running = True
        await self._websocket.send_json({"event": "status_update", "status": "RUNNING"})
        await self._websocket.send_json({
            "stream": "stdout", 
            "data": f"--- Fake sandbox {self.sandbox_id} started ---\n"
        })
        # Start a background task to handle messages
        self._task = asyncio.create_task(self._message_loop())
        print(f"Fake sandbox {self.sandbox_id}: STARTED.")

    async def _message_loop(self):
        try:
            while self.is_running:
                data = await self._websocket.receive_text()
                await self._websocket.send_json({
                    "stream": "stdout", 
                    "data": f"[ECHO] {data}"
                })
        except Exception:
            print(f"Fake sandbox {self.sandbox_id}: Connection closed.")
        finally:
            await self.stop()

    async def stop(self):
        print(f"Fake sandbox {self.sandbox_id}: STOPPING.")
        self.is_running = False
        if self._task:
            self._task.cancel()
            self._task = None
        if self._websocket:
            await self._websocket.close(code=1000)
            self._websocket = None
        print(f"Fake sandbox {self.sandbox_id}: STOPPED.")

    async def delete(self):
        print(f"Fake sandbox {self.sandbox_id}: DELETING.")
        await self.stop()
        # In a real implementation, this would delete files from GCS.
        print(f"Fake sandbox {self.sandbox_id}: DELETED.")

class GVisorSandbox(SandboxInterface):
    """The real gVisor sandbox implementation. (To be implemented later)"""
    def __init__(self, sandbox_id):
        self._sandbox_id = sandbox_id

    @property
    def sandbox_id(self):
        raise NotImplementedError

    async def create(self, code: str):
        raise NotImplementedError

    async def start(self, websocket):
        raise NotImplementedError

    async def stop(self):
        raise NotImplementedError

    async def delete(self):
        raise NotImplementedError
