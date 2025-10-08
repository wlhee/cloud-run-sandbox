"""
Data class for representing and interpreting the state of a distributed lock.
"""
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class LockData:
    """
    Wraps the raw lock data dictionary and provides helper properties for easy state
    checking.
    """

    raw: Dict[str, Any]

    @property
    def owner_id(self) -> Optional[str]:
        return self.raw.get("ownerId")

    @property
    def generation(self) -> Optional[int]:
        return self.raw.get("generation")

    @property
    def is_expired(self) -> bool:
        """Checks if the lock's main lease has expired."""
        return self.raw.get("expiresAt", 0) < time.time()

    @property
    def waiting_owner_id(self) -> Optional[str]:
        return self.raw.get("waitingOwnerId")

    @property
    def has_waiter(self) -> bool:
        """Checks if a waiter is registered, regardless of expiration."""
        return self.raw.get("waitingOwnerId") is not None

    @property
    def is_waiter_expired(self) -> bool:
        """Checks if the registered waiter's lease has expired."""
        return self.raw.get("waiterExpiresAt", 0) < time.time()
