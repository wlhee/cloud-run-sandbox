import asyncio
from dataclasses import dataclass, field
from typing import List
from .interface import SandboxInterface, SandboxCreationError, SandboxStartError
from .events import SandboxOutputEvent, OutputType

@dataclass
class FakeSandboxConfig:
    """Configuration for the FakeSandbox."""
    create_should_fail: bool = False
    start_should_fail: bool = False
    output_messages: List[SandboxOutputEvent] = field(default_factory=list)

class FakeSandbox(SandboxInterface):
    """
    A configurable, fake, in-memory sandbox for testing.
    """
    def __init__(self, sandbox_id, config: FakeSandboxConfig = None):
        self._sandbox_id = sandbox_id
        self._config = config or FakeSandboxConfig()
        self._output_queue = asyncio.Queue()
        self._task = None
        self.is_running = False

    @property
    def sandbox_id(self):
        return self._sandbox_id

    async def create(self):
        if self._config.create_should_fail:
            raise SandboxCreationError("Fake sandbox failed to create as configured.")
        print(f"Fake sandbox {self.sandbox_id}: CREATED.")
        await asyncio.sleep(0.01)

    async def start(self, code: str):
        if self._config.start_should_fail:
            raise SandboxStartError("Fake sandbox failed to start as configured.")
        
        print(f"Fake sandbox {self.sandbox_id}: STARTING.")
        self.is_running = True
        self._task = asyncio.create_task(self._produce_output())
        print(f"Fake sandbox {self.sandbox_id}: STARTED.")

    async def _produce_output(self):
        """Puts the configured messages onto the output queue."""
        for message in self._config.output_messages:
            await self._output_queue.put(message)
            await asyncio.sleep(0.01)
        self.is_running = False

    async def connect(self):
        """Yields SandboxOutputEvent objects from the sandbox."""
        while self.is_running or not self._output_queue.empty():
            try:
                message = await asyncio.wait_for(self._output_queue.get(), timeout=1.0)
                yield message
            except asyncio.TimeoutError:
                break

    async def stop(self):
        print(f"Fake sandbox {self.sandbox_id}: STOPPING.")
        self.is_running = False
        if self._task:
            self._task.cancel()
            self._task = None
        print(f"Fake sandbox {self.sandbox_id}: STOPPED.")

    async def delete(self):
        print(f"Fake sandbox {self.sandbox_id}: DELETING.")
        await self.stop()
        print(f"Fake sandbox {self.sandbox_id}: DELETED.")
