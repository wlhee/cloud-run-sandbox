# Cloud Run Sandbox Python Client

A Python client for interacting with the Cloud Run Sandbox service.

## Installation

```bash
pip install .
```

## Usage

```python
import asyncio
from sandbox import Sandbox

async def main():
    # The URL should be the WebSocket endpoint of your deployed service,
    # typically "wss://<your-cloud-run-url>"
    sandbox = await Sandbox.create("wss://<CLOUD_RUN_URL>")

    # Execute a command
    process = await sandbox.exec("bash", "echo 'Hello from the sandbox!'")

    # Read the output
    output = await process.stdout.read_all()
    print(output)

    # Terminate the sandbox
    await sandbox.terminate()

if __name__ == "__main__":
    asyncio.run(main())
```
