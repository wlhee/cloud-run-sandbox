# GVisorSandbox Refactoring Plan

This document outlines a step-by-step plan to refactor the `GVisorSandbox` implementation for clarity, robustness, and correctness. The core goals are to address confusion between different types of IDs, implement a strict state machine, and standardize process management.

---

### Phase 1: Introduce a Consistent `Process` Abstraction [DONE]

The goal is to replace the special-purpose `Execution` class with a general `Process` class that can be used for *any* process we manage, including the main sandbox process and subsequent `exec` commands.

1.  **Create `src/sandbox/process.py`**: A new file will be created to house the new abstraction.
2.  **Implement the `Process` Class**:
    *   This class will be a wrapper around an `asyncio.subprocess.Process` instance.
    *   It will manage the lifecycle of the subprocess (starting, terminating).
    *   It will provide an `async for` interface to stream combined `stdout` and `stderr` events, similar to the current `connect()` method. This will be the single, consistent way we get output from any process.
    *   It will have a `write_to_stdin()` method.
3.  **Add Unit Tests for `Process`**: A new test file `tests/unit/sandbox/test_process.py` will be created to validate the functionality of the new `Process` class in isolation.
4.  **Commit**: The new `Process` class and its tests will be committed with the message `feat(sandbox): Introduce Process abstraction`.

---

### Phase 2: Refactor `GVisorSandbox` Core Logic

This is the main phase where we will implement the new architecture based on the `Process` abstraction. This will be broken down into smaller, atomic commits.

1.  **Differentiate Sandbox ID vs. Container ID [DONE]**:
    *   **Change**: In `gvisor.py`, the internal `_sandbox_id` will be renamed to `_container_id`. The `__init__` method will take a persistent, client-facing `sandbox_id`.
    *   **Test**: Update `tests/unit/sandbox/test_gvisor_sandbox.py` to reflect this change in the constructor.
    *   **Commit**: Commit with message `refactor(gvisor): Differentiate between sandbox_id and container_id`.

2.  **Implement the `Process` Model for `create` and `restore`**:
    *   **Change**: Modify `gvisor.py`:
        *   Add a `self._main_process: Process = None` attribute.
        *   Remove the `--detach` flag from all `runsc` commands.
        *   Update `create()` and `restore()` to use `asyncio.create_subprocess_exec` and the new `Process` class, storing the result in `self._main_process`.
        *   Implement an immediate error-checking mechanism after process launch to detect and raise startup failures.
        *   Update `delete()` to terminate `self._main_process`.
    *   **Test**: Update `tests/unit/sandbox/test_gvisor_sandbox.py` to adjust the tests for `create`, `restore`, and `delete` to account for the new process management.
    *   **Commit**: Commit with message `refactor(gvisor): Adopt Process model for main sandbox lifecycle`.

3.  **Replace `Execution` with `Process`**:
    *   **Change**: Modify `gvisor.py`:
        *   Replace `self._current_execution` with `self._exec_process: Process = None`.
        *   Update the `execute()` method to use the `Process` class instead of the `Execution` class.
        *   Update `connect()` and `write_to_stdin()` to work with `self._exec_process`.
    *   **Change**: Delete the file `src/sandbox/execution.py`.
    *   **Test**: Update `tests/unit/sandbox/test_gvisor_sandbox.py` to reflect the changes to `execute`, `connect`, and `write_to_stdin`.
    *   **Test**: Delete the now-obsolete test file `tests/unit/sandbox/test_execution.py`.
    *   **Commit**: Commit with message `refactor(gvisor): Replace Execution with Process abstraction`.

4.  **Enforce State Machine**:
    *   **Change**: In `gvisor.py`, add explicit state checks at the beginning of public methods (`execute`, `checkpoint`, `restore`, `delete`) to enforce a valid lifecycle.
    *   **Test**: Add new tests to `tests/unit/sandbox/test_gvisor_sandbox.py` that specifically verify these state transitions (e.g., asserting that `checkpoint()` raises an error if the sandbox is not in the `RUNNING` state).
    *   **Commit**: Commit with message `feat(gvisor): Enforce strict state machine`.

---
