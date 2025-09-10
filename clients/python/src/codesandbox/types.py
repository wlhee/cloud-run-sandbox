from enum import Enum

class MessageKey(str, Enum):
    """
    Top-level keys in the JSON messages from the server.
    """
    EVENT = "event"
    STATUS = "status"
    DATA = "data"
    SANDBOX_ID = "sandbox_id"
    MESSAGE = "message"

class EventType(str, Enum):
    """
    Values for the 'event' key in a server message.
    """
    STATUS_UPDATE = "status_update"
    SANDBOX_ID = "sandbox_id"
    STDOUT = "stdout"
    STDERR = "stderr"
    ERROR = "error"

class SandboxEvent(str, Enum):
    """
    Values for the 'status' key when the event is 'status_update'.
    """
    SANDBOX_CREATING = "SANDBOX_CREATING"
    SANDBOX_RUNNING = "SANDBOX_RUNNING"
    SANDBOX_NOT_FOUND = "SANDBOX_NOT_FOUND"
    SANDBOX_IN_USE = "SANDBOX_IN_USE"
    SANDBOX_CREATION_ERROR = "SANDBOX_CREATION_ERROR"
    
    SANDBOX_EXECUTION_RUNNING = "SANDBOX_EXECUTION_RUNNING"
    SANDBOX_EXECUTION_DONE = "SANDBOX_EXECUTION_DONE"
    SANDBOX_EXECUTION_ERROR = "SANDBOX_EXECUTION_ERROR"
