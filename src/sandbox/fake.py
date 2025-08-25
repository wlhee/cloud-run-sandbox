import asyncio
from dataclasses import dataclass, field
from typing import List
from .interface import SandboxInterface, SandboxCreationError, SandboxStartError
from .events import SandboxOutputEvent

@dataclass
class FakeSandboxConfig:
    """Configuration for the FakeSandbox."""
    create_should_fail: bool = False
    start_should_fail: bool = False
    output_messages: List[SandboxOutputEvent] = field(default_factory=list)

class FakeSandbox(SandboxInterface):
    """
    A configurable, fake, in-memory sandbox for testing. It supports
    multiple concurrent connections.
    """
    def __init__(self, sandbox_id, config: FakeSandboxConfig = None):
        self._sandbox_id = sandbox_id
        self._config = config or FakeSandboxConfig()
        self.is_running = False

    @property
    def sandbox_id(self):
        return self._sandbox_id

    async def create(self):
        if self._config.create_should_fail:
            raise SandboxCreationError("Fake sandbox failed to create as configured.")
        print(f"Fake sandbox {self.sandbox_id}: CREATED.")
        await asyncio.sleep(0.01)

    async def execute(self, code: str):
        if self._config.start_should_fail:
            raise SandboxStartError("Fake sandbox failed to start as configured.")
        
        print(f"Fake sandbox {self.sandbox_id}: EXECUTING.")
        self.is_running = True
        print(f"Fake sandbox {self.sandbox_id}: EXECUTED.")

    async def connect(self):
        """
        Yields the configured output messages. This is an async generator
        that can be consumed by multiple clients.
        """
        for message in self._config.output_messages:
            yield message
            await asyncio.sleep(0.01) # Simulate network delay

    async def stop(self):
        print(f"Fake sandbox {self.sandbox_id}: STOPPING.")
        self.is_running = False
        print(f"Fake sandbox {self.sandbox_id}: STOPPED.")

    async def delete(self):
        print(f"Fake sandbox {self.sandbox_id}: DELETING.")
        await self.stop()
        print(f"Fake sandbox {self.sandbox_id}: DELETED.")