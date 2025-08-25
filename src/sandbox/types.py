from enum import Enum
from typing import TypedDict

class CodeLanguage(Enum):
    """Enumeration for the supported code languages."""
    PYTHON = "python"
    BASH = "bash"

class OutputType(Enum):
    """Enumeration for the type of sandbox output stream."""
    STDOUT = "stdout"
    STDERR = "stderr"

class SandboxOutputEvent(TypedDict):
    """
    A TypedDict representing a single output event from a sandbox.
    'type' indicates the stream (stdout or stderr), and 'data' is the content.
    """
    type: OutputType
    data: str

class SandboxStateEvent(Enum):
    """Enumeration for the lifecycle state events of a sandbox."""
    # The sandbox is being created and initialized.
    SANDBOX_CREATING = "SANDBOX_CREATING"
    # The sandbox is running and ready to process code.
    SANDBOX_RUNNING = "SANDBOX_RUNNING"
    # The requested sandbox could not be found on any active instance.
    SANDBOX_NOT_FOUND = "SANDBOX_NOT_FOUND"
    # A non-recoverable error occurred during the initial creation of the sandbox.
    SANDBOX_CREATION_ERROR = "SANDBOX_CREATION_ERROR"
    # A non-recoverable error occurred while trying to start the code execution.
    SANDBOX_START_ERROR = "SANDBOX_START_ERROR"