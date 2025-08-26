# Cloud Run Sandbox

This project provides a web server that can execute Python code in a sandboxed environment on Google Cloud Run using gVisor (`runsc`).

## 1. Deployment

To deploy this application to Cloud Run, you will need to have the `gcloud` CLI installed and authenticated. Then, run the following command from the root of the project directory:

```bash
gcloud run deploy sandbox --source . --project=<YOUR_PROJECT_ID> --region=us-central1 --allow-unauthenticated --execution-environment=gen2 --concurrency=1
```

Replace `<YOUR_PROJECT_ID>` with your Google Cloud project ID.

## 2. Executing Python or Bash Code

To execute a Python or Bash script, you can send a POST request to the `/execute` endpoint with the content of the script as the request body, and `language=[python|bash]` as a query parameter.

For example, to execute the `test_hello.py` script in `example` directory:

```bash
curl -s -X POST -H "Content-Type: text/plain" --data-binary @example/test_hello.py https://<YOUR_SERVICE_URL>/execute?language=python
```

For bash scripts,

```bash
curl -s -X POST -H "Content-Type: text/plain" --data "echo 'hello from bash'" https://<YOUR_SERVICE_URL>/execute?language=bash
```

Replace `<YOUR_SERVICE_URL>` with the URL of your deployed Cloud Run service. The output of the script will be available in the Cloud Run logs.

## 3. Container Management

You can manage the running sandboxes using the following endpoints:

### List Containers

To list all running containers:

```bash
curl https://<YOUR_SERVICE_URL>/list
```

### Suspend a Container

To suspend a running container, you will need its ID from the `/list` endpoint.

```bash
curl https://<YOUR_SERVICE_URL>/suspend/<CONTAINER_ID>
```

### Restore a Container

To restore a suspended container:

```bash
curl https://<YOUR_SERVICE_URL>/restore/<CONTAINER_ID>
```

### Delete a Container

To delete a container:

```bash
curl https://<YOUR_SERVICE_URL>/delete/<CONTAINER_ID>
```

## 4. Limitation

Currently, the sandbox environment does not support importing non-standard Python libraries.

**TODO:** Add support for installing and using third-party libraries.