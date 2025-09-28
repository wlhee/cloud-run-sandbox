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
    # An error occurred during the execution of code in the sandbox.
    SANDBOX_EXECUTION_ERROR = "SANDBOX_EXECUTION_ERROR"
    # The sandbox is executing code.
    SANDBOX_EXECUTION_RUNNING = "SANDBOX_EXECUTION_RUNNING"
    # The sandbox has finished executing code.
    SANDBOX_EXECUTION_DONE = "SANDBOX_EXECUTION_DONE"
    # The sandbox is already in use by another client.
    SANDBOX_IN_USE = "SANDBOX_IN_USE"
    # An error occurred while writing to stdin.
    SANDBOX_STDIN_ERROR = "SANDBOX_STDIN_ERROR"
    # The sandbox is being checkpointed.
    SANDBOX_CHECKPOINTING = "SANDBOX_CHECKPOINTING"
    # The sandbox has been successfully checkpointed.
    SANDBOX_CHECKPOINTED = "SANDBOX_CHECKPOINTED"
    # An error occurred during the checkpointing of the sandbox.
    SANDBOX_CHECKPOINT_ERROR = "SANDBOX_CHECKPOINT_ERROR"
    # The sandbox is being restored from a checkpoint.
    SANDBOX_RESTORING = "SANDBOX_RESTORING"
    # An error occurred during the restoration of the sandbox.
    SANDBOX_RESTORE_ERROR = "SANDBOX_RESTORE_ERROR"
    # A checkpoint was attempted while an execution was in progress.
    SANDBOX_EXECUTION_IN_PROGRESS_ERROR = "SANDBOX_EXECUTION_IN_PROGRESS_ERROR"
