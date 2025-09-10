# Cloud Run Sandbox Python Client

A Python client for interacting with the Cloud Run Sandbox service.

## Installation

```bash
pip install .
```

## Usage

```python
import asyncio
from codesandbox import Sandbox

async def main():
    # Create a new sandbox
    sandbox = await Sandbox.create("ws://localhost:8000")

    # Execute a command
    process = await sandbox.exec("echo 'Hello from the sandbox!'", "bash")

    # Read the output
    output = await process.stdout.read()
    print(output)

    # Terminate the sandbox
    await sandbox.terminate()

if __name__ == "__main__":
    asyncio.run(main())
```
