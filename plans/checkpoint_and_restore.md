# Checkpoint-and-Restore Handoff Implementation Plan

This document outlines the step-by-step plan to implement stateful sandbox handoffs using a checkpoint-and-restore mechanism with GCS as the persistence layer.

### **Design & Plan**

The core idea is to treat GCS as the source of truth for a sandbox's state. A running instance holds a "lease" on the sandbox, but its persistent state resides in a dedicated GCS directory. This allows a new instance to take over by restoring that state.

---

#### **Phase 1: Core Sandbox Checkpoint/Restore API [DONE]**

This phase focuses on establishing the `checkpoint` and `restore` contract and implementing it at the lowest level of the sandbox abstraction.

1.  **Update `SandboxInterface` (`src/sandbox/interface.py`)**
    *   Add two new abstract methods to the `SandboxInterface` class to enforce the pattern on all implementations:
        ```python
        @abstractmethod
        async def checkpoint(self, checkpoint_path: str) -> None:
            pass

        @abstractmethod
        async def restore(self, checkpoint_path: str) -> None:
            pass
        ```

2.  **Implement in `FakeSandbox` (`src/sandbox/fake.py`)**
    *   Implement `checkpoint`: It will create a dummy file at `checkpoint_path` to simulate a state save.
    *   Implement `restore`: It will check for the existence of the dummy file at `checkpoint_path`. This ensures our unit tests can validate the manager's logic without a real gVisor dependency.

3.  **Implement in `GVisorSandbox` (`src/sandbox/gvisor.py`)**
    *   **State Management**: The class will gain an internal state property (e.g., `self._state`) to track if it's `RUNNING`, `CHECKPOINTED`, etc.
    *   **`checkpoint()` Logic**:
        *   **Precondition**: Can only be called when the sandbox is idle (no active `SandboxExecution`). Will raise a `SandboxOperationError` if a process is running.
        *   It will use the `runsc checkpoint --image-path <path> <sandbox_id>` command.
        *   The `--leave-running` flag will **not** be used, as the instance should relinquish control after checkpointing. The container will be stopped.
    *   **`restore()` and Lifecycle Refactoring**:
        *   The existing `create()` method's logic will be split. A new `_prepare_bundle()` method will handle creating the OCI `config.json`.
        *   `restore()` will call `_prepare_bundle()` and then use `runsc restore --image-path <path> --bundle <bundle_dir> <sandbox_id>` to start the container from the saved state.
        *   `create()` will be simplified to call `_prepare_bundle()` and then `runsc run --detach ...`.
    *   **Interaction with `SandboxExecution`**:
        *   Under the "idle-only" checkpoint rule, a restored sandbox will always start with `self._current_execution = None`. The existing `execute()` method will work correctly for new commands. We are explicitly deferring the complexity of restoring an in-flight execution.

---

#### **Phase 2: Manager Orchestration with GCS Volume Mount [DONE]**

1.  **[DONE] Explicitly Configure the `SandboxManager`**:
    *   Modify the `SandboxManager` in `src/sandbox/manager.py` to accept an optional `checkpoint_and_restore_path: str` during initialization.
    *   If this path is not provided, checkpointing and restore functionality will be disabled.

2.  **[DONE] Update Sandbox Creation Logic**:
    *   **`websocket.py`**: The `_setup_create` method will be updated to look for a new boolean field, `enable_checkpoint`, in the initial "create" message from the client.
    *   **`manager.py`**: The `create_sandbox` method will be modified to accept the `enable_checkpoint` flag.
        *   It will check if the manager is configured with a `checkpoint_and_restore_path` and if the client sent `enable_checkpoint: true`.
        *   **Requirement**: If `enable_checkpoint` is `true`, the manager will **enforce** that the sandbox configuration uses `network="sandbox"` and will allocate a unique IP address for it.
        *   If both conditions are met, the manager will create the sandbox directory (`<checkpoint_and_restore_path>/<sandbox_id>/`) and the initial `metadata.json` directly on the mounted GCS volume.

3.  **[DONE] Implement `checkpoint_sandbox` Method**:
    *   **`manager.py`**: The new `checkpoint_sandbox(sandbox_id)` method will:
        1.  Construct the full checkpoint path directly on the mounted volume: `{self.checkpoint_and_restore_path}/{sandbox_id}/checkpoint`.
        2.  Call the sandbox instance's `checkpoint()` method, passing this direct path.
        3.  Update the `metadata.json` on the mounted volume.
    *   **`websocket.py`**: The handler will be updated to recognize the `{"action": "checkpoint"}` message and call the manager's new method.

4.  **[DONE] Implement Implicit Restore on "Attach"**:
    *   **`manager.py`**: The `get_sandbox(sandbox_id)` method will be updated:
        1.  On a cache miss, it will check for the existence of the directory `{self.checkpoint_and_restore_path}/{sandbox_id}/`.
        2.  If it exists, it will create a new sandbox instance and call its `restore()` method, passing the direct path to the checkpoint on the mounted volume.

5.  **[DONE] Support for Multiple Checkpoints**:
    *   The current implementation only supports a single checkpoint per sandbox, overwriting it each time.
    *   The system needs to be enhanced to manage multiple, named checkpoints (e.g., using tags or timestamps).
    *   The `checkpoint` action in the WebSocket protocol will need to be updated to accept a name or tag for the checkpoint.
    *   The `restore` mechanism will need to be updated to allow a client to specify which checkpoint to restore from.

---

#### **Phase 4: GCS-Based Locking & Handoff Protocol**

This phase implements the distributed lock and the full handoff protocol, ensuring that only one Cloud Run instance can operate on a sandbox's state at any given time.

1.  **Implement GCS Locking (`src/sandbox/manager.py`)**
    *   Create two new private helper methods in the `SandboxManager`: `_acquire_lock(sandbox_id)` and `_release_lock(sandbox_id)`.
    *   `_acquire_lock` will attempt to atomically create a lock file (e.g., `/gcs/sandboxes/<sandbox_id>/sandbox.lock`). The file's content should identify the current instance. If the file already exists, the lock is considered taken, and the method should fail.
    *   `_release_lock` will simply delete the lock file.

2.  **Integrate Locking into Manager Operations (`src/sandbox/manager.py`)**
    *   **`checkpoint_sandbox()`**: Must acquire the lock before creating the checkpoint and release it afterward.
    *   **`get_sandbox()` (Restore Logic)**: This is the heart of the handoff.
        *   On a cache miss, before checking for the GCS state, it **must acquire the lock**.
        *   If locking fails, it means another instance is already performing a handoff. The manager should raise a specific exception that the WebSocket handler can translate into a `SANDBOX_IN_USE` or a new `SANDBOX_HANDOFF_IN_PROGRESS` status.
        *   If locking succeeds, it can safely restore the sandbox and then **release the lock** once the sandbox is running.

3.  **Implement the Relinquish Mechanism (The "Watcher")**
    *   This is the most complex part of the handoff. The original instance (`Instance A`) needs to know when to save its state because another instance (`Instance B`) wants to take over.
    *   A background task will be needed. For now, we can simplify this: when `Instance A`'s WebSocket connection is closed (the client disconnects), instead of immediately deleting the sandbox, it will perform a final **checkpoint** before shutting down. This makes its state available for the next instance that receives an "attach" request.
