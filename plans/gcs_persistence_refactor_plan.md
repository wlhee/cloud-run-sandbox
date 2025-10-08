# GCS Persistence and Locking Refactor Plan

This document outlines the implementation plan for refactoring the GCS-backed sandbox functionality based on the finalized design in `docs/gcs_bucket_structure.md`.

## Phase 1: Refactor Configuration & Data Structures

1.  **Introduce New Configuration Module:**
    - Create a new file `src/sandbox/config.py`.
    - This module will be responsible for parsing and validating all GCS-related environment variables:
        - `SANDBOX_LOCK_BUCKET`
        - `SANDBOX_METADATA_BUCKET` / `SANDBOX_METADATA_MOUNT_PATH`
        - `SANDBOX_CHECKPOINT_BUCKET` / `SANDBOX_CHECKPOINT_MOUNT_PATH`
        - `FILESYSTEM_SNAPSHOT_BUCKET` / `FILESYSTEM_SNAPSHOT_MOUNT_PATH`
    - It should provide a singleton or a simple function to access the validated configuration throughout the application.

2.  **Update Data Types:**
    - Modify `src/sandbox/types.py`.
    - Update the relevant data classes to match the new `metadata.json` format.

3.  **Validation Strategy:**
    - **No Startup Validation:** The server will always start, regardless of which GCS environment variables are set. Its capabilities are determined at runtime.
    - **Validation at Request Time:** The server must validate it can support all requested features at the time of the request.
        - **`create_sandbox(gcs_sandbox_id=...)`**: This is the primary validation point. The server will check for the presence of `SANDBOX_LOCK_BUCKET` and `SANDBOX_METADATA_BUCKET`. If they are not configured, the API call will fail immediately.
        - **`checkpoint()`**: When this API is called, the server will check for `SANDBOX_CHECKPOINT_BUCKET` / `..._MOUNT_PATH`. If not configured, the call fails.
        - **`snapshot()`**: When this API is called, the server will check for `FILESYSTEM_SNAPSHOT_BUCKET` / `..._MOUNT_PATH`. If not configured, the call fails.

## Phase 2: Isolate GCS Logic in the Sandbox Manager

1.  **Centralize Path Logic in `manager.py`:**
    - Modify `src/sandbox/manager.py`.
    - The `SandboxManager` will import and use the new configuration module from `src/sandbox/config.py`.
    - Implement the core path resolution logic: for a given artifact, check for a `_MOUNT_PATH` environment variable first. If present, combine it with the relative path from the metadata to create a full local path. If not, fall back to constructing a `gs://` URI from the corresponding `_BUCKET` variable.
    - This manager will be the single component responsible for creating the final path string (local or GCS) for an artifact.

2.  **Update `gvisor.py`:**
    - Modify `src/sandbox/gvisor.py`.
    - The `GVisorSandbox` class will be updated to accept a path to a snapshot archive (`.tar.gz`).
    - Implement the sandbox creation/restore logic:
        1. Create a new temporary directory to serve as the sandbox rootfs.
        2. Based on the path format (local vs. `gs://`), either copy the archive from the local path or download it from GCS.
        3. Extract the archive into the newly created rootfs directory.
        4. Start the sandbox using this prepared directory.

3.  **Update `factory.py`:**
    - Modify `src/sandbox/factory.py`.
    - Update the `SandboxFactory` to pass the new GCS configuration parameters from the API request into the `SandboxManager`.

## Phase 3: Update Locking and Tests

1.  **Refactor `GCSLock`:**
    - Modify `src/sandbox/lock/gcs.py`.
    - Update the `GCSLock` class to be initialized using the `SANDBOX_LOCK_BUCKET` provided by the new configuration module.

2.  **Update Unit & Integration Tests:**
    - **`test_config.py`**: Add a new test file to verify the logic in the new config module.
    - **`test_gcs.py`**: Update the lock tests to mock the new configuration system.
    - **`test_manager.py`**: Add extensive new tests to verify the path resolution logic for all modes (mounted vs. GCS client) and the request-time validation logic.
    - **`test_gvisor_sandbox.py`**: Add tests to verify the archive download and extraction logic.
    - **Integration Tests**: Update integration tests in `tests/integration/` to cover the full end-to-end lifecycle of creating, attaching, and detaching a GCS-backed sandbox using the new configuration.
