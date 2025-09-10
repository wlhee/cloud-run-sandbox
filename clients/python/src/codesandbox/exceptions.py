class SandboxException(Exception):
    """Base exception for the sandbox client."""
    pass

class SandboxConnectionError(SandboxException):
    """Raised when there is an issue with the WebSocket connection."""
    pass

class SandboxCreationError(SandboxException):
    """Raised when the server fails to create a sandbox."""
    pass

class SandboxExecutionError(SandboxException):
    """Raised when the server reports an error during code execution."""
    pass
