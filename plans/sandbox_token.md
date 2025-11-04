# Sandbox Token Feature Plan

This document outlines the plan to add a "sandbox_token" feature for security purposes.

## 1. Interface (`interface.py`)

- Add `set_sandbox_token(self, sandbox_id: str, token: str) -> None` to the `ISandbox` interface.
- `FakeSandbox`:
  - Implement `set_sandbox_token` to store the token in memory.
  - Implement `get_sandbox_token` to retrieve the token from memory.
- `GVisorSandbox`:
  - Implement `set_sandbox_token` to use `runc exec` to write the token to a file at a well-known location within the sandbox.
  - Implement `get_sandbox_token` to use `runc exec` to read the token from the file.
- `SandboxManager`:
  - In `create_sandbox`, after successfully creating the sandbox instance:
    - Generate a secure, random token.
    - Call `set_sandbox_token` on the sandbox instance.
    - Return the token along with the sandbox ID.
- `handle_create` (WebSocket handler):
- In the `attach` method:
    - Accept the token from the client.
    - Call `get_sandbox_token` on the sandbox instance.
    - Compare the client token with the sandbox token and raise an exception if they don't match.
- Add tests for this new logic in `tests/unit/sandbox/test_manager.py`.

## 5. Python Client (`clients/python/src/sandbox/sandbox.py`)

- Modify the `create` method to store the returned token.
- Modify the `attach` method to send the token to the server.
- Update tests in `clients/python/tests/test_sandbox.py`.

## 6. JavaScript Client (`clients/js/src/sandbox.ts`)

- Modify the `create` method to store the returned token.
- Modify the `attach` method to send the token to the server.
- Update tests in `clients/js/tests/sandbox.test.ts`.
