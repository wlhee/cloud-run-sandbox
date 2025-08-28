from abc import ABC, abstractmethod
from .types import SandboxOutputEvent, CodeLanguage

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
    async def stop(self):
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
