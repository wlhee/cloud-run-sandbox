# Cloud Run Sandbox TypeScript Client

A TypeScript client for interacting with the Cloud Run Sandbox service.

## Installation

```bash
npm install
```

## Usage

```typescript
import { Sandbox } from './src/sandbox';

async function main() {
  // The URL should be the WebSocket endpoint of your deployed service,
  // typically "wss://<your-cloud-run-url>"
  const sandbox = await Sandbox.create('wss://<CLOUD_RUN_URL>');

  // Execute a command
  const process = await sandbox.exec('bash', "echo 'Hello from the sandbox!'");

  // Read the output
  for await (const chunk of process.stdout) {
    console.log(chunk.toString());
  }

  // Kill the sandbox
  sandbox.kill();
}

main().catch(console.error);
```

## Development

### Setup
```bash
npm install
```

### Running Tests
```bash
npm test
```
