from abc import ABC, abstractmethod
from enum import Enum
from .types import SandboxOutputEvent, CodeLanguage

class SandboxState(str, Enum):
    """Represents the lifecycle state of a sandbox."""
    INITIALIZED = "INITIALIZED"
    RUNNING = "RUNNING"
    CHECKPOINTED = "CHECKPOINTED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"

class SandboxError(Exception):
    """Base exception for sandbox-related errors."""
    pass

class SandboxCreationError(SandboxError):
    """Raised when a sandbox fails to create."""
    pass

class SandboxOperationError(SandboxError):
    """Raised when an operation on a sandbox fails."""
    pass

class SandboxExecutionError(SandboxOperationError):
    """Raised when code execution within a sandbox fails."""
    pass

class SandboxStreamClosed(SandboxError):
    """Raised by the connect() generator when the output stream is closed."""
    pass

class SandboxInterface(ABC):
    """Defines the interface for all sandbox implementations."""
    
    @property
    @abstractmethod
    def sandbox_id(self):
        pass

    @property
    def is_attached(self) -> bool:
        return False

    @is_attached.setter
    def is_attached(self, value: bool):
        pass

    @abstractmethod
    async def create(self):
        """
        Performs initial setup for the sandbox.
        Raises SandboxCreationError on failure.
        """
        pass

    @abstractmethod
    async def execute(self, language: CodeLanguage, code: str):
        """
        Executes code in the sandbox.
        Raises SandboxOperationError on failure.
        """
        pass

    @abstractmethod
    async def delete(self):
        pass

    @abstractmethod
    async def connect(self):
        """
        Yields a stream of SandboxOutputEvent objects one at a time.
        
        A SandboxOutputEvent is a dictionary-like object (a TypedDict) with a
        fixed structure: {'type': OutputType, 'data': str}.

        Raises SandboxStreamClosed when the stream is finished.
        """
        pass

    @abstractmethod
    async def write_to_stdin(self, data: str):
        """
        Writes data to the stdin of the running process.
        """
        pass

    @abstractmethod
    async def checkpoint(self, checkpoint_path: str) -> None:
        """
        Creates a checkpoint of the sandbox's state.
        """
        pass

    @abstractmethod
    async def restore(self, checkpoint_path: str) -> None:
        """
        Restores the sandbox's state from a checkpoint.
        """
        pass