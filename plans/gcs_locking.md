# GCS-Based Distributed Lock with Handoff Signaling

This document outlines a revised, iterative plan to implement a distributed lock. This design prioritizes testability (both unit and integration) and includes a critical new feature: a handoff signaling mechanism to allow instances to gracefully transfer sandbox ownership.

The core of this design is a `LockInterface` that will be implemented by both a real `GCSLock` and a `FakeLock` for testing, enabling dependency injection.

---

### **Phase 1: Core Lock Abstraction & Fake Implementation [DONE]**

**Goal**: Define a robust, testable interface for the lock and create an in-memory fake implementation. This allows us to develop and test the application logic without any GCS dependency.

1.  **Create `src/sandbox/lock_interface.py`**
    *   Define the `LockInterface` ABC, including new exceptions for the single-waiter model.

    ```python
    # src/sandbox/lock_interface.py
    from abc import ABC, abstractmethod
    from typing import Callable

    class LockError(Exception):
        """Base exception for lock-related errors."""
        pass

    class LockTimeoutError(LockError):
        """Raised when acquiring a lock times out while waiting."""
        pass

    class LockContentionError(LockError):
        """Raised when trying to acquire a lock that already has a waiter."""
        pass

    class LockInterface(ABC):
        @abstractmethod
        async def acquire(self, timeout_sec: int = 30) -> None:
            """
            Asynchronously acquires the lock, waiting if necessary.

            Raises:
                LockContentionError: If the lock is held and another instance
                                     is already waiting for the handoff.
                LockTimeoutError: If the lock cannot be acquired within the
                                  specified timeout after becoming the waiter.
            """
            pass

        @abstractmethod
        async def release(self) -> None:
            """Asynchronously releases the lock. Should be idempotent."""
            pass

        @abstractmethod
        async def renew(self) -> None:
            """
            Asynchronously renews the lease. Triggers the handoff callback if a
            waiter is detected for the first time.
            """
            pass

        @abstractmethod
        def on_release_requested(self, handler: Callable[[], None]) -> None:
            """
            Registers a handler to be invoked when another process requests the lock.
            """
            pass
    ```

2.  **Create `src/sandbox/fake_lock.py`**: Implement an in-memory `FakeLock` that respects the single-waiter logic and throws the correct exceptions.

3.  **Create `tests/unit/sandbox/test_fake_lock.py`**: Write unit tests for `FakeLock`, including tests for the new `LockContentionError` scenario.

---

### **Phase 2: GCS Lock Implementation & Unit Tests [DONE]**

**Goal**: Implement the real `GCSLock` and validate it with mocked unit tests.

1.  **Update `requirements.txt`**: Add `google-cloud-storage`.

2.  **Create `src/sandbox/gcs_lock.py`**
    *   Implement `GCSLock` inheriting from `LockInterface`.

    *   **Detailed Lock Behavior (Single-Waiter Model)**:
        *   The GCS lock object will be a JSON file containing `ownerId`, `expiresAt`, and a nullable `waitingOwnerId` string.
        *   The `GCSLock` class will use an internal `_handoff_signaled` flag to ensure the handoff callback is invoked only once.

        *   **`acquire(timeout_sec)` Logic**:
            1.  Attempt to acquire the lock immediately if it is free or expired.
            2.  If the lock is held, check the `waitingOwnerId` in the GCS object.
            3.  If `waitingOwnerId` is `null`, atomically set it to the current instance's ID. Then, enter an internal polling loop, waiting up to `timeout_sec` for the lock to be released.
            4.  If `waitingOwnerId` is **already taken**, immediately raise `LockContentionError` (fail-fast).
            5.  If the timeout is reached while polling, raise `LockTimeoutError`.

        *   **`renew()` Logic**:
            1.  The owner calls this periodically.
            2.  If `waitingOwnerId` is not `null` AND the internal `_handoff_signaled` flag is `False`, set the flag to `True` and invoke the `on_release_requested` handler **exactly once**.
            3.  Then, renew the lease by updating `expiresAt`.

        *   **`release()` Logic**:
            1.  Atomically deletes the lock object from GCS.
            2.  Resets the internal `_handoff_signaled` flag to `False`.


3.  **Create `tests/unit/sandbox/test_gcs_lock.py`**
    *   Write unit tests for `GCSLock`.
    *   These tests will use `unittest.mock` to create a fake GCS client, bucket, and blob. This allows testing of the GCS-specific logic (precondition failures, object parsing, etc.) in complete isolation.

---

### **Phase 3: Integration into SandboxManager**

**Goal**: Refactor `SandboxManager` to use the lock abstraction via dependency injection, ensuring it is fully testable at the integration level.

1.  **Refactor `SandboxManager` for Dependency Injection**
    *   The `__init__` method will be modified to accept a `lock_factory` callable (e.g., `lambda sandbox_id: GCSLock(...)`).
    *   This removes the hard dependency on `GCSLock`, allowing us to inject `FakeLock` during integration tests.

    ```python
    # src/sandbox/manager.py excerpt
    class SandboxManager:
        def __init__(self, lock_factory: Callable[[str], LockInterface], ...):
            self._lock_factory = lock_factory
            # ...
    ```

2.  **Integrate Locking Logic**
    *   In `restore_sandbox` and `checkpoint_sandbox`, use `self._lock_factory(sandbox_id)` to get a lock instance.
    *   Use a `try...finally` block to ensure `lock.release()` is always called.
    *   A background task will be created to periodically call `lock.renew()` for every active, in-memory sandbox. This renewal task is what will drive the handoff mechanism.

3.  **Update Integration Tests (e.g., `tests/integration/test_server.py`)**
    *   When initializing `SandboxManager` for tests, pass it a `FakeLock` factory: `lock_factory=lambda sandbox_id: FakeLock(...)`.
    *   This ensures integration tests run without any external GCS calls.
    *   Add new integration tests to verify correct locking behavior, such as preventing a second client from attaching to a locked sandbox.