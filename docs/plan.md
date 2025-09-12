# Checkpoint-and-Restore Handoff Implementation Plan

This document outlines the step-by-step plan to implement stateful sandbox handoffs using a checkpoint-and-restore mechanism with GCS as the persistence layer.

### **Design & Plan**

The core idea is to treat GCS as the source of truth for a sandbox's state. A running instance holds a "lease" on the sandbox, but its persistent state resides in a dedicated GCS directory. This allows a new instance to take over by restoring that state.

---

#### **Phase 1: Core Sandbox Checkpoint/Restore API**

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
    *   **`checkpoint()` Logic**:
        *   It will use the `docker checkpoint create <container_id> <checkpoint_name>` command. The `checkpoint_path` will be a directory managed by Docker.
        *   **Lifecycle Constraint**: A critical design decision is handling active processes. For this initial implementation, we will enforce that a sandbox can only be checkpointed when it is **idle** (i.e., no active `SandboxProcess`). If `checkpoint()` is called while a process is running, it will raise a `SandboxStateError`. This simplifies the initial design and avoids the complexity of saving in-flight process state.
    *   **`restore()` Logic**:
        *   This is a multi-step process that changes how containers are started. Instead of `docker run`, a restored sandbox will use:
            1.  `docker create ...` to create the container from the image without starting it.
            2.  `docker start --checkpoint <checkpoint_name> <container_id>` to start the container from the saved state.
        *   The `GVisorSandbox` will need to be adapted to handle both the standard "start fresh" and this new "restore" lifecycle.

---

#### **Phase 2: Manager-Level Orchestration**

The `SandboxManager` will be the central orchestrator for all persistence operations, interacting with both the sandbox instances and GCS.

1.  **GCS Directory Structure (`src/sandbox/manager.py`)**
    *   The manager will be configured with a GCS root path, e.g., `/gcs/sandboxes/`.
    *   When a new sandbox is created via `create_sandbox()`, the manager will:
        1.  Generate a **globally unique ID** using `uuid.uuid4()`.
        2.  Create a dedicated directory: `/gcs/sandboxes/<sandbox_id>/`.
        3.  Inside this directory, create a `metadata.json` file containing initial info like `{"status": "created", "createdAt": "<timestamp>"}`.

2.  **Implement `checkpoint_sandbox()` (`src/sandbox/manager.py`)**
    *   A new public method, `checkpoint_sandbox(sandbox_id: str)`, will be added.
    *   It will retrieve the sandbox instance, determine the GCS path for the checkpoint (e.g., `/gcs/sandboxes/<sandbox_id>/checkpoint`), and call the sandbox's `checkpoint()` method.
    *   Upon success, it will update the `metadata.json` to `{"status": "checkpointed", "lastCheckpointedAt": "<timestamp>"}`.

3.  **Implicit Restore on "Attach" (`src/sandbox/manager.py`)**
    *   The `get_sandbox(sandbox_id: str)` method will be updated to handle the handoff scenario:
        1.  It will first check its in-memory cache (`self._sandboxes`).
        2.  **If not found (cache miss)**, it will check for the existence of `/gcs/sandboxes/<sandbox_id>/`.
        3.  If the GCS directory and a checkpoint exist, it will:
            a. Create a new `GVisorSandbox` instance using the factory.
            b. Call the new instance's `restore()` method with the path to the checkpoint.
            c. Add the now-hydrated sandbox to the in-memory cache.
            d. Return the restored sandbox.
        4.  If no GCS state is found, it will correctly return `None` to signal a `SANDBOX_NOT_FOUND` condition.

---

#### **Phase 3: Exposing via WebSocket API**

Finally, we will expose this new capability to the client through the WebSocket connection.

1.  **Handle "checkpoint" Action (`src/handlers/websocket.py`)**
    *   The WebSocket message handling loop will be updated to recognize a new client message:
        ```json
        {
          "action": "checkpoint"
        }
        ```
    *   Upon receiving this, the handler will call `await self.manager.checkpoint_sandbox(self.sandbox.id)`.
    *   It will then send a confirmation status update to the client.

2.  **Add New `SandboxEvent` Type (`src/sandbox/types.py`)**
    *   To inform the client about the successful checkpoint, a new event status will be added to the `SandboxEvent` enum:
        ```python
        SANDBOX_CHECKPOINTED = "SANDBOX_CHECKPOINTED"
        ```

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
