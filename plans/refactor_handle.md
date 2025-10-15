# SandboxHandle Refactor Plan [*DONE*]

This document outlines a plan to refactor the `SandboxHandle` to use an explicit factory pattern for lifecycle management, ensuring clarity, safety, and a robust API.

## 1. Core Principles

1.  **Explicit Factory Methods**: The `SandboxHandle` will no longer be instantiated directly via its `__init__` constructor from outside the class. Instead, it will provide three distinct class method factories, each corresponding to a specific lifecycle event. This makes the caller's intent completely unambiguous.

2.  **Atomic Creation**: The factory methods for persistent sandboxes ensure that the creation process is atomic. A handle is only returned if all steps (validation, directory creation, file I/O) succeed. This prevents the existence of partially initialized or "zombie" objects.

3.  **Separation of Concerns**:
    - **`SandboxManager` (The "Should I?")**: This manager remains responsible for high-level policy and server capability checks.
    - **`SandboxHandle` (The "How and Where?")**: The handle remains the single source of truth for all path generation and now also manages the atomicity of its own creation.

4.  **Decoupling "Persistent" from "Snapshot"**:
    - **Persistent Sandbox**: A sandbox created with the intent to be checkpointed and restored, defined by a `metadata.json` file.
    - **Filesystem Snapshot**: A feature available to *any* sandbox (persistent or ephemeral), as long as the server is configured for it.

## 2. The Three-Factory Design

### Step 1: Simplify `SandboxHandle.__init__`

The `__init__` method will be simplified to a basic data setter. It will not be called directly from outside the class. Its only job is to initialize the in-memory state of a handle.

### Step 2: Implement `SandboxHandle.create_ephemeral(...)` Factory

- **Purpose**: To create a basic, temporary, in-memory sandbox handle.
- **Process**:
    1.  Accepts basic arguments (`sandbox_id`, `instance`, `idle_timeout`, and optionally `gcs_config` if snapshotting is needed).
    2.  Calls the simplified `__init__` to create a standard `SandboxHandle` instance.
    3.  Returns the new, non-persistent handle.

### Step 3: Implement `SandboxHandle.create_persistent(...)` Factory

- **Purpose**: To create a **new** persistent (checkpointable) sandbox and establish its permanent record on GCS.
- **Process**:
    1.  **Validate**: Checks if the server's `gcs_config` can support the requested `enable_sandbox_checkpoint` feature.
    2.  **Instantiate**: Calls the simple `__init__` to create the base handle object.
    3.  **Prepare Metadata**: Creates the `GCSSandboxMetadata` object in memory.
    4.  **Persist**: Creates the `sandboxes/<sandbox_id>/` directory and performs the initial, durable write of the `metadata.json` file.
    5.  **Return**: Returns the fully initialized, persistent handle.

### Step 4: Implement `SandboxHandle.attach_persistent(...)` Factory

- **Purpose**: To create a handle for an **existing** persistent sandbox by loading its state from GCS.
- **Process**:
    1.  **Read**: Reads and parses the `metadata.json` from the GCS mount.
    2.  **Validate**: Validates the metadata's contents against the current server's configuration.
    3.  **Instantiate**: Calls the simple `__init__` to create the base handle.
    4.  **Hydrate**: Populates the new handle with the loaded and validated `gcs_metadata`.
    5.  **Return**: Returns the fully configured handle.

### Step 5: Role of `filesystem_snapshot_file_path(...)`

This method remains on the `SandboxHandle` and is available on all handles (persistent or ephemeral) that have a `gcs_config`. It generates the correct path for a given snapshot ID.

## 3. Iteration Plan

We will proceed with a **code -> test** cycle for each factory.
1.  **Code**: Implement the simplified `__init__` and the `create_ephemeral` and `create_persistent` factories in `src/sandbox/handle.py`.
2.  **Test**: Create a new test file from scratch.
3.  **Test Case 1**: Add a test to validate the behavior of `SandboxHandle.create_ephemeral`.
4.  **Test Case 2**: Add a test to validate the behavior of `SandboxHandle.create_persistent`.
5.  Repeat for the `attach_persistent` factory.
