import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Type
from .interface import SandboxInterface, SandboxCreationError, SandboxOperationError, SandboxStreamClosed
from .types import SandboxOutputEvent, CodeLanguage, SandboxStateEvent

logger = logging.getLogger(__name__)

@dataclass
class ExecConfig:
    """Configuration for a single execution within the FakeSandbox."""
    output_stream: List[SandboxOutputEvent] = field(default_factory=list)
    expected_language: Optional[CodeLanguage] = None
    expected_code: Optional[str] = None
    expected_stdin: List[str] = field(default_factory=list)
    exec_error: Optional[Type[Exception]] = None
    connect_error: Optional[Type[Exception]] = None

@dataclass
class FakeSandboxConfig:
    """Configuration for the FakeSandbox."""
    create_should_fail: bool = False
    executions: List[ExecConfig] = field(default_factory=list)

class FakeSandbox(SandboxInterface):
    """
    A configurable, fake, in-memory sandbox for testing that supports
    scripted responses for multiple, sequential executions.
    """
    def __init__(self, sandbox_id, config: FakeSandboxConfig = None):
        self._sandbox_id = sandbox_id
        self._config = config or FakeSandboxConfig()
        self.is_running = False
        self._exec_count = 0
        self._is_attached = False

    @property
    def sandbox_id(self):
        return self._sandbox_id

    @property
    def is_attached(self) -> bool:
        return self._is_attached

    @is_attached.setter
    def is_attached(self, value: bool):
        self._is_attached = value

    async def create(self):
        if self._config.create_should_fail:
            raise SandboxCreationError("Fake sandbox failed to create as configured.")
        logger.info(f"Fake sandbox {self.sandbox_id}: CREATED.")
        await asyncio.sleep(0.01)

    async def execute(self, language: CodeLanguage, code: str):
        if self.is_running:
            raise SandboxOperationError("An execution is already in progress.")

        current_exec_config = self._get_current_exec()
        if not current_exec_config:
            raise AssertionError("Unexpected call to execute().")

        # Verify expectations
        if current_exec_config.expected_language is not None:
            assert language == current_exec_config.expected_language
        if current_exec_config.expected_code is not None:
            assert code == current_exec_config.expected_code
        
        # Raise a configured error, if any
        if current_exec_config.exec_error:
            raise current_exec_config.exec_error("Fake sandbox failed to execute as configured.")

        logger.info(f"Fake sandbox {self.sandbox_id}: EXECUTING ({self._exec_count + 1}).")
        self.is_running = True
        logger.info(f"Fake sandbox {self.sandbox_id}: EXECUTED.")

    async def connect(self):
        """
        Yields the configured output messages for the current execution.
        """
        current_exec_config = self._get_current_exec()
        if not current_exec_config:
            return

        if current_exec_config.connect_error:
            raise current_exec_config.connect_error("Fake sandbox failed to connect as configured.")

        yield {"type": "status_update", "status": SandboxStateEvent.SANDBOX_EXECUTION_RUNNING.value}

        for message in current_exec_config.output_stream:
            yield message
            await asyncio.sleep(0.01)
        
        yield {"type": "status_update", "status": SandboxStateEvent.SANDBOX_EXECUTION_DONE.value}
        
        self.is_running = False
        self._exec_count += 1
        raise SandboxStreamClosed()

    def _get_current_exec(self) -> Optional[ExecConfig]:
        if self._exec_count < len(self._config.executions):
            return self._config.executions[self._exec_count]
        return None

    async def stop(self):
        logger.info(f"Fake sandbox {self.sandbox_id}: STOPPING.")
        self.is_running = False
        logger.info(f"Fake sandbox {self.sandbox_id}: STOPPED.")

    async def delete(self):
        logger.info(f"Fake sandbox {self.sandbox_id}: DELETING.")
        await self.stop()
        logger.info(f"Fake sandbox {self.sandbox_id}: DELETED.")

    async def write_to_stdin(self, data: str):
        """Writes data to the stdin of the process."""
        logger.info(f"Fake sandbox {self.sandbox_id}: writing to stdin: {data}")
        current_exec_config = self._get_current_exec()
        if not current_exec_config:
            raise AssertionError("Unexpected call to write_to_stdin().")

        if not current_exec_config.expected_stdin:
            raise AssertionError(f"Received unexpected stdin: {data}")

        expected_data = current_exec_config.expected_stdin.pop(0)
        assert data == expected_data