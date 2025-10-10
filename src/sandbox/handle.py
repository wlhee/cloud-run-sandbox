from dataclasses import dataclass, field
from typing import Optional, Callable
import asyncio
import time

from .config import GCSConfig


@dataclass
class GCSArtifact:
    """
    Represents a generic artifact stored in GCS.
    """
    # The GCS bucket name. Example: "my-sandbox-artifacts"
    bucket: str
    # The path to the artifact within the bucket. Example: "sandbox_checkpoints/ckpt-123/"
    path: str


@dataclass
class GCSSandboxMetadata:
    """
    Represents the structure of the metadata.json file in GCS. This is the persistent state.
    """
    # The unique ID of the sandbox. Example: "sandbox-abc-123"
    sandbox_id: str
    # Unix timestamp (seconds since epoch) of when the sandbox was created.
    created_timestamp: float
    # The idle timeout in seconds. Example: 300
    idle_timeout: Optional[int] = None
    # A GCSArtifact pointing to the latest checkpoint.
    latest_sandbox_checkpoint: Optional[GCSArtifact] = None


@dataclass
class SandboxHandle:
    """
    Represents the in-memory, runtime state of a sandbox being actively managed.
    """
    # The live sandbox object (e.g., a GVisorSandbox instance).
    instance: any
    # The idle timeout in seconds. Example: 300
    idle_timeout: int = None
    # The Unix timestamp of the last activity, used for idle cleanup.
    last_activity: float = field(default_factory=time.time)
    # The asyncio.Task responsible for idle cleanup.
    cleanup_task: asyncio.Task = None
    # An optional callback to invoke when the sandbox is deleted.
    delete_callback: Optional[Callable[[str], None]] = None
    # The IP address assigned to the sandbox if networking is enabled. Example: "192.168.100.5"
    ip_address: Optional[str] = None
