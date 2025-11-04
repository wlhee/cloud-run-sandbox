# Sandbox Token Feature Plan

This document outlines the plan to add a "sandbox_token" feature for security purposes.

## 1. Interface (`interface.py`)

- Add `create_sandbox_token(self, sandbox_id: str, token: str) -> None` to the `ISandbox` interface.
- Add `get_sandbox_token(self, sandbox_id: str) -> str` to the `ISandbox` interface.

## 2. Fake Sandbox (`fake.py`)

- Implement `create_sandbox_token` to store the token in memory.
- Implement `get_sandbox_token` to retrieve the token from memory.
- Add tests for these methods in `tests/unit/sandbox/test_fake_sandbox.py`.

## 3. gVisor Sandbox (`gvisor.py`)

- Implement `create_sandbox_token` to use `runc exec` to write the token to a file at a well-known location within the sandbox.
- Implement `get_sandbox_token` to use `runc exec` to read the token from the file.
- Add tests for these methods in `tests/unit/sandbox/test_gvisor_sandbox.py`.

## 4. Manager (`manager.py`)

- In the `create` method:
    - Generate a secure random token.
    - Call `create_sandbox_token` on the sandbox instance.
    - Return the token to the client.
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
