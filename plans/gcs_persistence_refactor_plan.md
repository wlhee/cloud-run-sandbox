# GCS Persistence and Locking Refactor Plan (Revised)

This document outlines the implementation plan for refactoring the GCS-backed sandbox functionality. The core of this refactor is the introduction of `SandboxHandle` as a centralized class for managing all state and configuration for a single sandbox instance, ensuring that logic for persistence is isolated and easily testable.

## Phase 1: Introduce `SandboxHandle` and Centralize Configuration

1.  **Introduce `src/sandbox/handle.py`:**
    - This new file will define the `SandboxHandle`, `GCSSandboxMetadata`, and `GCSArtifact` data classes.
    - The `SandboxHandle` will be the single source of truth for a sandbox's state, including:
        - **In-memory runtime data:** `instance`, `cleanup_task`, `last_activity`, `idle_timeout`, etc.
        - **Persistent state:** `gcs_config` and the loaded `gcs_metadata`.
    - It will centralize all path construction logic for GCS artifacts (metadata, lock files, checkpoints, snapshots).
    - It will contain methods for reading and writing the persistent `metadata.json` file.

2.  **Solidify `src/sandbox/config.py`:**
    - This module will remain the central point for parsing and validating all GCS-related environment variables.
    - It will provide a `GCSConfig` object that is passed to and stored within the `SandboxHandle`.

3.  **Add Comprehensive Tests for `SandboxHandle`:**
    - Create a new test file: `tests/unit/sandbox/test_handle.py`.
    - Add extensive unit tests to verify:
        - All path construction logic under various configurations (e.g., mounted vs. non-mounted paths).
        - Validation logic within the handle.
        - The correctness of reading and writing metadata to a mock filesystem.

## Phase 2: Integrate `SandboxHandle` into the Sandbox Manager

1.  **Refactor `src/sandbox/manager.py`:**
    - The `SandboxManager` will be refactored to delegate all persistence logic to the `SandboxHandle`.
    - It will maintain a dictionary of active `SandboxHandle` instances, keyed by `sandbox_id`.
    - The `GCSConfig` is passed to the `SandboxManager` on initialization (in `main.py`). The manager will then pass this config to the `SandboxHandle` when a new sandbox is created.
    - All sandbox operations (create, get, checkpoint, snapshot) will be mediated through the corresponding `SandboxHandle`.
        - **Creation/Restore:** The manager will create a `SandboxHandle` and use it to read the `metadata.json` from GCS to restore a sandbox's state.
        - **Checkpoint/Snapshot:** The manager will use the handle to determine the correct paths for storing artifacts, and then use the handle to update and persist the new metadata.

2.  **Centralize Validation in `SandboxHandle`:**
    - All validation logic will be moved from the manager into the `SandboxHandle`.
    - At the time of a request, the handle will validate that the server has the necessary GCS configuration to support the requested feature (e.g., checkpointing requires `SANDBOX_CHECKPOINT_BUCKET`). If not, the operation will fail early.

3.  **Update `gvisor.py`:**
    - The `GVisorSandbox` will not be aware of the `SandboxHandle`. It will continue to accept simple paths for archives, which will be provided by the `SandboxManager` after being resolved by the `SandboxHandle`.

## Phase 3: Update Locking and Tests

1.  **Refactor `GCSLock`:**
    - The `GCSLock` in `src/sandbox/lock/gcs.py` will be updated to use the `GCSConfig` object.
    - The `SandboxManager` will use the `lock_path` property from the `SandboxHandle` to determine the correct path for the lock file.

2.  **Update Unit & Integration Tests:**
    - **`test_handle.py`**: As described in Phase 1, this will be a new and comprehensive test suite.
    - **`test_manager.py`**: Tests will be updated to mock the `SandboxHandle` and verify that the manager correctly uses the handle to manage the sandbox lifecycle.
    - **`test_gcs.py`**: The lock tests will be updated to mock the new configuration system.
    - **Integration Tests**: The tests in `tests/integration/` will be updated to cover the full end-to-end lifecycle of creating, attaching, and detaching a GCS-backed sandbox using the new `SandboxHandle`-based architecture.