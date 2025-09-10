# Cloud Run Sandbox

This project provides a web server that can execute Python code in a sandboxed environment on Google Cloud Run using gVisor (`runsc`).

## 1. Deployment

To deploy this application to Cloud Run, you will need to have the `gcloud` CLI installed and authenticated. Then, run the following command from the root of the project directory:

```bash
gcloud run deploy sandbox --source . --project=<YOUR_PROJECT_ID> --region=us-central1 --allow-unauthenticated --execution-environment=gen2 --concurrency=1
```

Replace `<YOUR_PROJECT_ID>` with your Google Cloud project ID.

## 2. Using the Python Client Library

The most convenient way to interact with the sandbox is by using the Python client library located in the `clients/python` directory.

Here is a simple example of how to connect to the sandbox, execute a command, and print its output:

```python
from codesandbox import Sandbox

# Replace `https` with `wss` of the Cloud Run service URL.
url = "wss://<YOUR_SERVICE_URL>"
sandbox = await Sandbox.create(url)

# Execute a command
process = await sandbox.exec("echo 'Hello from the sandbox!'", "bash")

# Read the output
stdout = await process.stdout.read()
print(f"STDOUT: {stdout}")

# Clean up the sandbox session
await sandbox.terminate()
```

For a more detailed and robust example that includes secure SSL/TLS setup, please see `example/client_example.py`.

## 3. Executing Python or Bash Code via HTTP (One-off testing)

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

## 4. Limitation

Currently, the sandbox environment does not support importing non-standard Python libraries.

**TODO:** Add support for installing and using third-party libraries.