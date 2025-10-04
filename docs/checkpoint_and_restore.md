# Checkpoint and Restore

This document outlines the checkpoint and restore functionality, enabling stateful sandboxes that can be persisted and handed off between server instances.

## Server Configuration

For the checkpoint and restore feature to be available, the server must be started with the `CHECKPOINT_AND_RESTORE_PATH` environment variable set to a valid path on a persistent volume. If this variable is not set, the server will reject any client requests to enable checkpointing and will not attempt to restore sandboxes from disk.

## Filesystem Structure

When checkpointing is enabled for a sandbox, the following directory structure is created within the path specified by the `CHECKPOINT_AND_RESTORE_PATH` environment variable:

```
/path/to/persistent/volume/
└── {sandbox_id}/
    ├── checkpoints/
    │   ├── checkpoint_1678886400000.img
    │   ├── checkpoint_1678886460000.img
    │   └── latest
    └── metadata.json
```

-   **`{sandbox_id}/`**: A directory unique to each sandbox.
-   **`metadata.json`**: A file containing metadata about the sandbox, such as its `idle_timeout`.
-   **`checkpoints/`**: A directory containing all checkpoint files for the sandbox.
-   **`checkpoint_{timestamp}.img`**: A timestamped file representing a single checkpoint of the sandbox's state.
-   **`latest`**: A simple text file that contains the filename of the most recent checkpoint (e.g., `checkpoint_1678886460000.img`). When a sandbox is restored, the server uses this file to identify which checkpoint to load.

This structure allows for multiple checkpoints to be stored for each sandbox, with the `latest` file ensuring that the most recent checkpoint is always used for restoration.

## Overview

The checkpoint and restore feature allows a client to save the complete state of a sandbox, including its filesystem and running processes, to a persistent volume. The sandbox can then be destroyed from the current server instance. At a later time, a client can reconnect to a different server instance, and the sandbox will be restored from the persistent volume to the exact state it was in when it was checkpointed.

## Enabling Checkpoint Functionality

To use this feature, the client must explicitly enable it when creating a new sandbox. This is done by sending an `enable_checkpoint: true` flag in the initial configuration message over the WebSocket.

**Example Creation Message:**
```json
{
  "idle_timeout": 300,
  "enable_checkpoint": true
}
```
If the server is not configured to support checkpointing, it will respond with a `SANDBOX_CREATION_ERROR` and close the connection.

## The Checkpoint Flow

A checkpoint is a terminal operation for the current WebSocket session. Once initiated, the connection will be closed by the server, whether the operation succeeds or fails (with one exception, noted below).

1.  **Client Initiates Checkpoint**: The client sends a JSON message to request a checkpoint.
    ```json
    {"action": "checkpoint"}
    ```
2.  **Server Acknowledges**: The server immediately sends a status update to indicate that the process has begun.
    ```json
    {"event": "status_update", "status": "SANDBOX_CHECKPOINTING"}
    ```
3.  **Successful Checkpoint**: If the checkpoint is successful, the server sends a final status update and closes the connection cleanly.
    ```json
    {"event": "status_update", "status": "SANDBOX_CHECKPOINTED"}
    ```
    The WebSocket will then be closed with code `1000` (Normal Closure).

## The Restore Flow

When a client attempts to attach to a sandbox ID that is not in the server's in-memory cache, the server will attempt to restore it from the persistent volume.

1.  **Client Initiates Attach**: The client connects to the `/attach/{sandbox_id}` WebSocket endpoint.
2.  **Server Acknowledges**: If the sandbox is not in memory but a checkpoint is found on the persistent volume, the server sends a status update to indicate a restore is in progress.
    ```json
    {"event": "status_update", "status": "SANDBOX_RESTORING"}
    ```
3.  **Successful Restore**: Once the sandbox is fully restored, the server sends the standard `SANDBOX_RUNNING` status, and the session proceeds as normal.
    ```json
    {"event": "status_update", "status": "SANDBOX_RUNNING"}
    ```

## Error Scenarios

Clients should be prepared to handle the following error flows.

### 1. Checkpoint During an Active Execution

This is a recoverable error. The checkpoint will fail, but the original code execution will continue, and the WebSocket connection will remain open.

- **Flow**:
    1. Client sends `{"action": "checkpoint"}` while a command is running.
    2. Server sends `{"event": "status_update", "status": "SANDBOX_CHECKPOINTING"}`.
    3. Server detects the conflict and sends `{"event": "status_update", "status": "SANDBOX_EXECUTION_IN_PROGRESS_ERROR"}`.
    4. Server sends an error message: `{"event": "error", "message": "Cannot checkpoint while an execution is in progress."}`.
- **Result**: The connection remains open. The client can continue to interact with the sandbox and will receive the output from the original command once it completes.

### 2. General Checkpoint Failure

This is a fatal error for the session. It occurs if the underlying `runsc` command fails for any reason other than an active execution.

- **Flow**:
    1. Client sends `{"action": "checkpoint"}`.
    2. Server sends `{"event": "status_update", "status": "SANDBOX_CHECKPOINTING"}`.
    3. The checkpoint fails.
    4. Server sends `{"event": "status_update", "status": "SANDBOX_CHECKPOINT_ERROR"}`.
    5. Server sends a descriptive error message: `{"event": "error", "message": "..."}`.
- **Result**: The WebSocket connection is closed by the server with code `4000` (Application-specific error).

### 3. Restore Failure: Checkpoint Not Found

This occurs if the client tries to attach to a sandbox ID that does not exist in memory or on the persistent volume.

- **Flow**:
    1. Client connects to `/attach/{sandbox_id}`.
    2. Server sends `{"event": "status_update", "status": "SANDBOX_RESTORING"}`.
    3. The server cannot find the checkpoint files.
    4. Server sends `{"event": "status_update", "status": "SANDBOX_NOT_FOUND"}`.
- **Result**: The WebSocket connection is closed by the server with code `1011` (Server error).

### 4. Restore Failure: Corrupted Checkpoint

This occurs if the checkpoint files are present but corrupted, and the restore operation fails.

- **Flow**:
    1. Client connects to `/attach/{sandbox_id}`.
    2. Server sends `{"event": "status_update", "status": "SANDBOX_RESTORING"}`.
    3. The restore operation fails.
    4. Server sends `{"event": "status_update", "status": "SANDBOX_RESTORE_ERROR"}`.
    5. Server sends a descriptive error message: `{"event": "error", "message": "..."}`.
- **Result**: The WebSocket connection is closed by the server with code `4000` (Application-specific error).
