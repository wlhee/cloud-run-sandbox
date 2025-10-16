# GCS Lock Integration Plan (Revised)

This document outlines the revised plan to integrate the GCS lock with the sandbox manager. The goal is to ensure that only one manager instance can operate on a persistent sandbox at any given time, and only when the sandbox is explicitly configured for handoff.

## 1. Update `SandboxHandle` to be Handoff-Aware

- Add a new attribute `enable_sandbox_handoff: bool = False` to the `SandboxHandle` dataclass.
- Add `lock: Optional[LockInterface] = None` to the `SandboxHandle` dataclass to hold the acquired lock.
- Modify `SandboxHandle.create_persistent` to accept an `enable_sandbox_handoff` argument and persist it in `metadata.json`.
- Modify `SandboxHandle.attach_persistent` to read `enable_sandbox_handoff` from `metadata.json` when attaching to an existing sandbox.

## 2. Modify `SandboxManager` for Conditional Locking

- **Inject Lock Factory:**
  - Add a `lock_factory: Optional[LockFactory]` parameter to the `SandboxManager.__init__` method. This will be an optional dependency.

- **Update `create_sandbox`:**
  - Add a new boolean parameter: `enable_sandbox_handoff: bool = False`.
  - **Conditional Locking:** Only attempt to acquire a lock if `enable_sandbox_handoff` is `True` and the `lock_factory` is configured.
  - If locking is required:
    - Create a lock for the `sandbox_id`.
    - Call `await lock.acquire()`. If it fails, raise a `SandboxCreationError`.
    - Pass the acquired `lock` and the `enable_sandbox_handoff` flag to the `SandboxHandle` upon its creation.

- **Update `restore_sandbox`:**
  - After attaching the `SandboxHandle` and loading its metadata, check if `handle.enable_sandbox_handoff` is `True`.
  - **Conditional Locking:** Only attempt to acquire a lock if the handle is marked for handoff and the `lock_factory` is configured.
  - If locking is required:
    - Create and acquire the lock. If it fails, raise a `SandboxRestoreError`.
    - Store the acquired `lock` in the `SandboxHandle`.

- **Update `delete_sandbox`:**
  - The logic here remains simple: when a sandbox is deleted, check if `handle.lock` exists.
  - If it does, call `await handle.lock.release()`. This naturally respects the conditional logic since the lock will only exist if it was acquired during creation or restoration.

## 3. Write Unit Tests for Conditional Locking

- **Location:** `tests/unit/sandbox/test_manager.py`
- **Strategy:** Use `unittest.mock.patch` to provide a mock `LockFactory` and `LockInterface`.

- **Test Cases:**
  - **`test_create_with_handoff_acquires_lock`**: Verify `lock.acquire()` is called when `create_sandbox` is called with `enable_sandbox_handoff=True`.
  - **`test_create_without_handoff_does_not_lock`**: Verify `lock.acquire()` is NOT called when `create_sandbox` is called with `enable_sandbox_handoff=False`.
  - **`test_restore_with_handoff_acquires_lock`**: Set up a `metadata.json` with `"enable_sandbox_handoff": true` and verify `lock.acquire()` is called during `restore_sandbox`.
  - **`test_restore_without_handoff_does_not_lock`**: Set up a `metadata.json` with `"enable_sandbox_handoff": false` (or missing the key) and verify `lock.acquire()` is NOT called.
  - **`test_delete_sandbox_releases_lock_if_present`**: Create a sandbox with handoff enabled, then delete it, and verify `lock.release()` is called.
  - **`test_restore_fails_if_lock_contended`**: Configure the mock `acquire()` to raise `LockContentionError` and assert that `restore_sandbox` (with handoff enabled) raises a `SandboxRestoreError`.

## 4. Run All Tests

- After implementing the changes and adding the new tests, run the entire test suite using `pytest` to ensure all functionality, both old and new, works as expected.
