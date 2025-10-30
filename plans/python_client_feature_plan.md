# Plan: Python Client Feature Parity

This plan is structured around a series of features to bring the Python client to full parity with the TypeScript client. For each feature, the process will be to implement the API, add corresponding unit tests, and, where applicable, create a new Python example file that mirrors the functionality of the TypeScript examples.

Use the TypeScript client implementation as a reference for business logic and error handling:
- TypeScript client code location: clients/js/src
- TypeScript client example location: examples/

---

#### **Feature 1: Debugging Support (Done)**
*   **Goal:** Add debug logging capabilities to the Python client for easier troubleshooting.
*   **Key API Additions:** `enable_debug` and `debug_label` parameters on `Sandbox.create()`.
*   **Implementation Steps:**
    1.  **`sandbox.py`**:
        *   Add `enable_debug` and `debug_label` parameters to the `create()` method.
        *   Store these flags on the `Sandbox` instance.
        *   Implement a private `_log_debug()` helper method that prints formatted debug messages if `enable_debug` is true.
        *   Add calls to `_log_debug()` in key areas: connection setup, message sending/receiving, and state transitions.
    2.  **`tests/unit/sandbox/test_sandbox.py`**: Add a new test to verify that debug logs are correctly generated when the feature is enabled and suppressed when disabled.

---

#### **Feature 2: Standalone Attach API (Done)**
*   **Goal:** Implement the ability to connect to a pre-existing sandbox instance using its ID.
*   **Key API Additions:** `Sandbox.attach(url, sandbox_id, ...)` class method.
*   **Implementation Steps:**
    1.  **`types.py`**: Add the necessary `SandboxEvent` enums for attach scenarios: `SANDBOX_NOT_FOUND` and `SANDBOX_IN_USE`.
    2.  **`sandbox.py`**:
        *   Implement the `attach(cls, url, sandbox_id, ...)` class method. It will connect to the `/attach/{sandbox_id}` WebSocket endpoint.
        *   Refactor the `__init__` and `_wait_for_creation` methods to handle the different initial states expected from `create` (starts with `SANDBOX_CREATING`) versus `attach` (expects `SANDBOX_RUNNING` immediately).
        *   Update the `_listen` loop to handle potential attachment errors (`SANDBOX_NOT_FOUND`, etc.).
    3.  **`tests/unit/sandbox/test_sandbox.py`**: Add new tests specifically for the `attach()` method, covering both successful attachment and failure cases.

---

#### **Feature 3: Core Lifecycle & Process Killing (Done)**
*   **Goal:** Establish the basic `create`/`exec` flow and add the ability to kill the sandbox and the running process, mirroring `lifecycle.ts`.
*   **Key API Additions:** `sandbox.kill()`, `process.kill()`
*   **TypeScript Example:** `lifecycle.ts`
*   **Python Example to Create:** `examples/lifecycle.py`
*   **Implementation Steps:**
    1.  **`types.py`**: Add `SANDBOX_KILLED`, `SANDBOX_KILL_ERROR`, `SANDBOX_EXECUTION_FORCE_KILLED` enums.
    2.  **`process.py`**: Add a `kill()` method to send a `kill_process` action.
    3.  **`tests/unit/sandbox/test_process.py`**: Add `test_process_kill` to test the new method.
    4.  **`sandbox.py`**: Rename `terminate()` to `kill()` for consistency and update it to send the `kill_sandbox` action.
    5.  **`tests/unit/sandbox/test_sandbox.py`**: Update tests to reflect the `terminate` -> `kill` rename.
    6.  **`examples/lifecycle.py`**: Create the new example file.

---

#### **Feature 4: Filesystem Snapshotting**
*   **Goal:** Implement the ability to create a sandbox from a filesystem snapshot and to create new snapshots, mirroring `filesystem_snapshot.ts`.
*   **Key API Additions:** `snapshot_filesystem()` method and `filesystem_snapshot_name` option on `create()`.
*   **TypeScript Example:** `filesystem_snapshot.ts`
*   **Python Example to Create:** `examples/filesystem_snapshot.py`
*   **Implementation Steps:**
    1.  **`types.py`**: Add `SANDBOX_FILESYSTEM_SNAPSHOT_CREATING`, `SANDBOX_FILESYSTEM_SNAPSHOT_CREATED`, `SANDBOX_FILESYSTEM_SNAPSHOT_ERROR` enums.
    2.  **`sandbox.py`**:
        *   Add `filesystem_snapshot_name` parameter to the `create()` method.
        *   Add the `snapshot_filesystem(name)` method.
        *   Update the internal message handler to process snapshot-related events.
    3.  **`tests/unit/sandbox/test_sandbox.py`**: Add tests for creating from a snapshot and for calling `snapshot_filesystem`.
    4.  **`examples/filesystem_snapshot.py`**: Create the new example file.

---

#### **Feature 5: Checkpointing**
*   **Goal:** Implement the ability to checkpoint a sandbox's state, mirroring `checkpoint.ts`.
*   **Key API Additions:** `checkpoint()` method and `enable_sandbox_checkpoint` option on `create()`.
*   **TypeScript Example:** `checkpoint.ts`
*   **Python Example to Create:** `examples/checkpoint.py`
*   **Implementation Steps:**
    1.  **`types.py`**: Add `SANDBOX_CHECKPOINTING`, `SANDBOX_CHECKPOINTED`, `SANDBOX_CHECKPOINT_ERROR` enums.
    2.  **`sandbox.py`**:
        *   Add `enable_sandbox_checkpoint` and `enable_idle_timeout_auto_checkpoint` parameters to `create()`.
        *   Add the `checkpoint()` method.
        *   Update the internal message handler for checkpoint events.
    3.  **`tests/unit/sandbox/test_sandbox.py`**: Add tests for creating with checkpointing enabled and for calling `checkpoint`.
    4.  **`examples/checkpoint.py`**: Create the new example file.

---

#### **Feature 6: Reconnection & Handoff**
*   **Goal:** Implement robust connection management, allowing clients to attach to existing sandboxes and automatically reconnect if the connection drops. This mirrors `reconnect.ts` and `handoff.ts`.
*   **Key API Additions:** `enable_auto_reconnect` and `enable_sandbox_handoff` options on `create()`.
*   **TypeScript Examples:** `reconnect.ts`, `handoff.ts`
*   **Python Examples to Create:** `examples/reconnect.py`, `examples/handoff.py`
*   **Implementation Steps:**
    1.  **`connection.py`**: Create this new file with a `Connection` class to manage the WebSocket, including reconnection logic.
    2.  **`tests/unit/sandbox/test_connection.py`**: Create a new test file for the `Connection` class.
    3.  **`types.py`**: Add `SANDBOX_RESTORING`, `SANDBOX_RESTORE_ERROR` enums.
    4.  **`sandbox.py`**:
        *   Refactor to use the new `Connection` class.
        *   Add `enable_auto_reconnect` and `enable_sandbox_handoff` parameters to `create()`.
        *   Implement the internal reconnection logic (`should_reconnect`, `get_reconnect_info`).
    5.  **`tests/unit/sandbox/test_sandbox.py`**: Add tests for handoff and auto-reconnection scenarios.
    6.  **`examples/reconnect.py` & `examples/handoff.py`**: Create the new example files.
