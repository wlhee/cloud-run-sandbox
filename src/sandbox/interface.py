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

class SandboxCheckpointError(SandboxOperationError):
    """Raised when a sandbox checkpoint operation fails."""
    pass

class SandboxExecutionInProgressError(SandboxCheckpointError):
    """Raised when a checkpoint is attempted during an active execution."""
    pass

class SandboxRestoreError(SandboxOperationError):
    """Raised when a sandbox restore operation fails."""
    pass

class SandboxSnapshotFilesystemError(SandboxOperationError):
    """Raised when a sandbox filesystem snapshot operation fails."""
    pass

class SandboxExecutionError(SandboxOperationError):
    """Raised when code execution within a sandbox fails."""
    pass

class SandboxStreamClosed(SandboxError):
    """Raised by the stream_outputs() generator when the output stream is closed."""
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
    async def stream_outputs(self):
        """
        Yields a stream of SandboxOutputEvent objects one at a time.
        
        A SandboxOutputEvent is a dictionary-like object (a TypedDict) with a
        fixed structure: {'type': OutputType, 'data': str}.

        Raises SandboxStreamClosed when the stream is finished.
        """
        pass

    @abstractmethod
    async def write_stdin(self, data: str):
        """
        Writes data to stdin of the running process.
        """
        pass

    @abstractmethod
    async def checkpoint(self, checkpoint_path: str, force: bool = False) -> None:
        """
        Creates a checkpoint of the sandbox's state.
        If force is True, the checkpoint will be created even if an execution
        is in progress.
        """
        pass

    @abstractmethod
    async def restore(self, checkpoint_path: str) -> None:
        """
        Restores the sandbox's state from a checkpoint.
        """
        pass

    @abstractmethod
    async def snapshot_filesystem(self, snapshot_path: str) -> None:
        """
        Creates a snapshot of the sandbox's filesystem.
        """
        pass