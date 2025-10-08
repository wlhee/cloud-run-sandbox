import time
import pytest

from src.sandbox.lock.data import LockData


def test_lock_data_properties():
    """Tests basic property access."""
    raw_data = {
        "ownerId": "owner-1",
        "generation": 123,
        "waitingOwnerId": "waiter-1",
    }
    lock_data = LockData(raw=raw_data)
    assert lock_data.owner_id == "owner-1"
    assert lock_data.generation == 123
    assert lock_data.waiting_owner_id == "waiter-1"


def test_is_expired():
    """Tests the is_expired property."""
    expired_data = LockData(raw={"expiresAt": time.time() - 100})
    assert expired_data.is_expired is True

    active_data = LockData(raw={"expiresAt": time.time() + 100})
    assert active_data.is_expired is False
