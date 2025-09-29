# JS Client Checkpoint and Restore Implementation Plan [DONE]


This document outlines the plan to implement checkpoint and restore functionality in the Javascript client.

## 1. Update `types.ts`

- Add new `SandboxEvent` members for checkpoint and restore to the `SandboxEvent` enum:
    - `SANDBOX_CHECKPOINTING`
    - `SANDBOX_CHECKPOINTED`
    - `SANDBOX_CHECKPOINT_ERROR`
    - `SANDBOX_EXECUTION_IN_PROGRESS_ERROR`
    - `SANDBOX_RESTORING`
    - `SANDBOX_RESTORE_ERROR`
    - `SANDBOX_NOT_FOUND`
- Add a new `EventType` for `ERROR`.

## 2. Update `sandbox.ts`

### `Sandbox.create()`

- Add an `enableCheckpoint` option to the `create` method.
- Send `enable_checkpoint: true` in the initial WebSocket message if the option is set.

### `Sandbox` class

- Add a new `checkpoint()` method. This method will send a `{"action": "checkpoint"}` message to the server. It should return a Promise that resolves when the checkpoint is complete, or rejects on error.
- The `checkpoint()` method needs to handle the `SANDBOX_CHECKPOINTING`, `SANDBOX_CHECKPOINTED`, and `SANDBOX_CHECKPOINT_ERROR` states.
- The `handleMessage` function will be updated to handle the new `SandboxEvent`s.
- Add an `attach()` static method to connect to an existing sandbox. It will take a `sandboxId` and connect to `/attach/{sandbox_id}`. This will be similar to `create()` but for existing sandboxes.

### State Management

- Add new states to `SandboxState` to represent checkpointing and restoring.
- The `handleMessage` and `handleClose` methods will need to be updated to correctly manage the sandbox's state during the checkpoint/restore process.
- Once a sandbox is successfully checkpointed, its state will be set to a terminal state (e.g., 'checkpointed') to prevent any further operations on it.

## 3. Update `process.ts`

- No changes are planned for `process.ts`. The server prevents checkpointing during active execution, so the client-side process management does not need to be aware of the checkpointing feature.

## 4. Add Tests

- A new test file `clients/js/tests/checkpoint.test.ts` will be created.
- Tests will cover:
    - Creating a sandbox with checkpointing enabled.
    - Checkpointing a sandbox.
    - Attaching to a checkpointed sandbox.
    - Handling checkpoint errors.
    - Verifying that a checkpointed sandbox cannot be used for further operations.