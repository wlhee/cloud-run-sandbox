# Cloud Run Sandbox

This project provides a web server that can execute Python code in a sandboxed environment on Google Cloud Run using gVisor (`runsc`).

## 1. Deployment

To deploy this application to Cloud Run, you will need to have the `gcloud` CLI installed and authenticated. Then, run the following command from the root of the project directory:

```bash
gcloud run deploy sandbox --source . --project=<YOUR_PROJECT_ID> --region=us-central1 --allow-unauthenticated --execution-environment=gen2 --concurrency=1
```

Replace `<YOUR_PROJECT_ID>` with your Google Cloud project ID.

## 2. Using the Client Libraries

The most convenient way to interact with the sandbox is by using one of the client libraries.

For each of these examples, ensure you first install the respective client in the clients/ folder. For example, `npm install clients/js/` for Typescript.

### Python

Here is a simple example of how to connect to the sandbox, execute a command, and print its output:

```python
from codesandbox import Sandbox

# Replace `https` with `wss` of the Cloud Run service URL.
url = "wss://<YOUR_SERVICE_URL>"
sandbox = await Sandbox.create(url)

# Execute a command
process = await sandbox.exec("echo 'Hello from the sandbox!'", "bash")

# Read the output
stdout = await process.stdout.read_all()
print(f"STDOUT: {stdout}")

# Clean up the sandbox session
await sandbox.terminate()
```

For a more detailed and robust example that includes secure SSL/TLS setup, please see `example/client_example.py`.

### TypeScript

Here is a simple example of how to connect to the sandbox, execute a command, and print its output:

```typescript
import { Sandbox } from './clients/js/src/sandbox';

// Replace `https` with `wss` of the Cloud Run service URL.
const url = "wss://<YOUR_SERVICE_URL>";
const sandbox = await Sandbox.create(url);

// Execute a command
const process = await sandbox.exec("echo 'Hello from the sandbox!'", "bash");

// Read the output
const stdout = await process.stdout.readAll();
console.log(`STDOUT: ${stdout}`);

// Clean up the sandbox session
sandbox.terminate();
```

For a more detailed example, please see `example/client_example.ts`.

## 3. Checkpoint and Restore

The sandbox supports stateful sessions through a checkpoint and restore mechanism. This allows a client to save the complete state of a sandbox (including its filesystem and running processes) to a persistent volume, disconnect, and later reconnect to a new server instance, restoring the sandbox to its exact previous state.

### Server Configuration

To enable this feature, the Cloud Run service must be deployed with a persistent volume and a specific environment variable of `CHECKPOINT_AND_RESTORE_PATH`.

1.  **Create a GCS Bucket**: First, ensure you have a Google Cloud Storage bucket to store the checkpoints.
2.  **Deploy with Volume Mount**: Deploy the service with the GCS bucket mounted as a volume.

Here is an example `gcloud` command:

```bash
gcloud run deploy sandbox --source . \
  --project=<YOUR_PROJECT_ID> \
  --region=us-central1 \
  --allow-unauthenticated \
  --execution-environment=gen2 \
  --concurrency=1 \
  --add-volume=name=gcs-volume,type=cloud-storage,bucket=<YOUR_BUCKET_NAME> \
  --add-volume-mount=volume=gcs-volume,mount-path=/mnt/checkpoint \
  --set-env-vars='CHECKPOINT_AND_RESTORE_PATH=/mnt/checkpoint'
```

Replace `<YOUR_PROJECT_ID>` and `<YOUR_BUCKET_NAME>` accordingly. If these are not configured, the server will reject any client requests to use the checkpointing feature.

### Example Usage

Here is a simplified example of the checkpoint/restore flow:

```typescript
// 1. Create a sandbox with checkpointing enabled
const sandbox1 = await Sandbox.create(url, { enableCheckpoint: true });
const sandboxId = sandbox1.sandboxId;

// 2. Checkpoint the sandbox
await sandbox1.checkpoint();

// 4. At a later time, attach to the sandbox to restore its state
const sandbox2 = await Sandbox.attach(url, sandboxId);
```

For a complete, runnable demonstration, please see the example file: `example/checkpoint.ts`.

## 4. Filesystem Snapshot

The sandbox supports creating a filesystem snapshot from a running sandbox. This allows a client to create a new sandbox from a snapshot, which can be faster than creating a new sandbox from scratch.

### Server Configuration

To enable this feature, the Cloud Run service must be deployed with a persistent volume and a specific environment variable of `FILESYSTEM_SNAPSHOT_PATH`.

1.  **Create a GCS Bucket**: First, ensure you have a Google Cloud Storage bucket to store the snapshots.
2.  **Deploy with Volume Mount**: Deploy the service with the GCS bucket mounted as a volume.

Here is an example `gcloud` command:

```bash
gcloud run deploy sandbox --source . \
  --project=<YOUR_PROJECT_ID> \
  --region=us-central1 \
  --allow-unauthenticated \
  --execution-environment=gen2 \
  --concurrency=1 \
  --add-volume=name=gcs-volume,type=cloud-storage,bucket=<YOUR_BUCKET_NAME> \
  --add-volume-mount=volume=gcs-volume,mount-path=/mnt/fs_snapshot \
  --set-env-vars='FILESYSTEM_SNAPSHOT_PATH=/mnt/fs_snapshot'
```

Replace `<YOUR_PROJECT_ID>` and `<YOUR_BUCKET_NAME>` accordingly. If these are not configured, the server will reject any client requests to use the filesystem snapshot feature.

### Example Usage

Here is a simplified example of the filesystem snapshot flow:

```typescript
// 1. Create a sandbox
const sandbox1 = await Sandbox.create(url);

// 2. Snapshot the sandbox filesystem
await sandbox1.snapshotFilesystem('my-snapshot');

// 3. At a later time, create a new sandbox from the snapshot
const sandbox2 = await Sandbox.create(url, { filesystemSnapshotName: 'my-snapshot' });
```

For a complete, runnable demonstration, please see the example file: `example/filesystem_snapshot.ts`.

## 5. Executing Python or Bash Code via HTTP (One-off testing)

To execute a Python or Bash script with HTTP, you can send a POST request to the `/execute`
endpoint with the content of the script as the request body, and `language=[python|bash]` as a
query parameter.

For example, to execute the `test_hello.py` script in `example` directory:

```bash
curl -s -X POST -H "Content-Type: text/plain" --data-binary @example/test_hello.py https://<YOUR_SERVICE_URL>/execute?language=python
```

For bash scripts,

```bash
curl -s -X POST -H "Content-Type: text/plain" --data "echo 'hello from bash'" https://<YOUR_SERVICE_URL>/execute?language=bash
```

Replace `<YOUR_SERVICE_URL>` with the URL of your deployed Cloud Run service. The output of the script will be available in the Cloud Run logs.

## 6. Limitation

Currently, the sandbox environment does not support importing non-standard Python libraries.

A simple way is workaround is to update the Dockerfile to install the libraries needed.

**TODO:** Add support for installing and using third-party libraries.