# API Updates for Advanced GCS Features

This document outlines the plan for future updates to the `create_sandbox` API to support advanced, GCS-dependent features. These changes should be implemented after the backend GCS refactoring is complete.

## 1. Goal

The goal is to extend the `create_sandbox` API to allow clients to request specific GCS-backed behaviors at the time of creation, and to ensure the server validates its ability to support these features before proceeding.

## 2. New `create_sandbox` API Parameters

The following new optional parameters will be added to the `create_sandbox` request body:

- **`gcs_sandbox_id` (string):** The ID of a new or existing GCS-backed sandbox. If provided, this enables the core persistence features.
- **`enable_handoff` (boolean):** If `True`, indicates the sandbox should be configured for handoff between server instances. This implies a dependency on checkpointing capabilities. Defaults to `False`.
- **`enable_checkpoint_at_idle` (boolean):** If `True`, the server will automatically create a checkpoint when the sandbox is idle for a configurable period. This also depends on checkpointing capabilities. Defaults to `False`.

## 3. API Validation Logic

The server will perform validation at the time a `create_sandbox` request is received, based on the combination of parameters provided.

| Parameters | Server Validation Logic | Failure Condition |
| :--- | :--- | :--- |
| **(No GCS params)** | No validation needed. Creates a standard ephemeral sandbox. | N/A |
| **`gcs_sandbox_id`** | Checks for `SANDBOX_LOCK_BUCKET` AND `SANDBOX_METADATA_BUCKET`. | Fails if either environment variable is not set. |
| **`gcs_sandbox_id` + `enable_handoff=True`** | Checks for `SANDBOX_LOCK_BUCKET`, `SANDBOX_METADATA_BUCKET`, AND `SANDBOX_CHECKPOINT_BUCKET` (or `..._MOUNT_PATH`). | Fails if any of the three required configurations are missing. |
| **`gcs_sandbox_id` + `enable_checkpoint_at_idle=True`** | Checks for `SANDBOX_LOCK_BUCKET`, `SANDBOX_METADATA_BUCKET`, AND `SANDBOX_CHECKPOINT_BUCKET` (or `..._MOUNT_PATH`). | Fails if any of the three required configurations are missing. |

This validation ensures that the server only accepts requests for features it is properly configured to support, providing clear and immediate feedback to the client.

## 4. Implementation Steps

1.  **Update API Specification:** Modify the OpenAPI (or equivalent) schema to include the new request parameters.
2.  **Update HTTP Handler:** Modify the `create_sandbox` handler in `src/handlers/http.py` to:
    - Accept the new parameters.
    - Import the configuration module (`src/sandbox/config.py`).
    - Implement the validation logic described in the table above.
    - Pass the validated parameters down to the `SandboxManager`.
3.  **Update `SandboxManager`:** Modify the manager to accept the new feature flags and implement the corresponding logic (e.g., setting up idle timers for auto-checkpointing).
4.  **Update Client Libraries:** Update the Python and TypeScript client libraries to support the new API parameters.
5.  **Add Tests:** Add new unit and integration tests to verify the validation logic and the functionality of the new features.
