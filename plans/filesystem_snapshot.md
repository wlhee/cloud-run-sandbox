# Filesystem Snapshot Feature Implementation Plan

This document outlines the plan to implement the filesystem snapshot feature.

## 1. Background

The goal is to leverage the upcoming `runsc` feature that allows creating filesystem snapshots and creating new sandboxes from these snapshots. This will improve sandbox startup performance.

The assumed `runsc` commands are:
- `runsc tar rootfs-upper --file=/path/to/tar`
- `runsc create --tar_path=/path/to/tar`

## 2. Implementation Steps

### 2.1. Sandbox Interface (`src/sandbox/interface.py`) - DONE

- [x] Add a new abstract method `snapshot_filesystem(self, snapshot_name: str) -> None`.

### 2.2. Sandbox Implementations (`src/sandbox/fake.py` and `src/sandbox/gvisor.py`) - DONE

- **`fake.py`**: Implement `snapshot_filesystem` as a no-op.
- **`gvisor.py`**:
    - [x] Implement `snapshot_filesystem` to execute the `runsc tar` command.
    - [x] Modify the `create` method to accept an optional `filesystem_snapshot_name: str | None = None`. If provided, use the `--tar_path` argument in the `runsc create` command.

### 2.3. Sandbox Manager (`src/sandbox/manager.py`) - DONE

- [x] Add a new configuration option `filesystem_snapshot_path: str | None`.
- [x] This will be configured via an environment variable, similar to `checkpoint_path`.
- [x] If `filesystem_snapshot_path` is not set, the feature should be disabled (e.g., raise an exception).
- [x] Expose a `snapshot_filesystem(self, sandbox_id: str, snapshot_name: str)` method that calls the underlying sandbox's method.
- [x] Modify `create_sandbox` to accept an optional `filesystem_snapshot_name` and pass it to the sandbox's `create` method.

### 2.4. WebSocket API (`src/handlers/websocket.py`) - DONE

- [x] Update the `create_sandbox` message handler to accept an optional `filesystem_snapshot_name` in the payload.
- [x] Pass this value to the `SandboxManager.create_sandbox` method.

### 2.5. JavaScript Client (`clients/js/src/sandbox.ts`)

- [ ] Update the `Sandbox.create` method to accept an optional `filesystemSnapshotName` parameter.
- [ ] Update the `SandboxInfo` type to include this new optional field.

### 2.6. Testing - Partially Done

- **`tests/unit/sandbox/test_gvisor_sandbox.py`**: - DONE
    - [x] Add tests for the `snapshot_filesystem` method, mocking `subprocess.run` and verifying the `runsc tar` command.
    - [x] Add tests for the modified `create` method to ensure the `--tar_path` argument is correctly added.
- **`tests/unit/sandbox/test_manager.py`**: - DONE
    - [x] Add tests for `snapshot_filesystem`, including the check for `filesystem_snapshot_path`.
    - [x] Add tests for `create_sandbox` with `filesystem_snapshot_name`.
- **`tests/unit/handlers/test_websocket.py`**: - 
    - [ ] Add tests for the `create_sandbox` handler with the new parameter.
    - [ ] Add tests for the `snapshot_filesystem` action
- **`clients/js/tests/sandbox.test.ts`**:
    - [ ] Add tests for creating a sandbox with `filesystemSnapshotName`.

## 3. Development Timeline

1.  [x] Implement changes to the sandbox interface, fake, and gVisor implementations.
2.  [x] Implement changes to the sandbox manager.
3.  [x] Write unit tests for the backend changes.
4.  [x] Expose the feature through the WebSocket API.
5.  [ ] Write integration tests.
6.  [ ] Update the JavaScript client.
7.  [ ] Write tests for the JavaScript client.
