# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import os
import ssl
import certifi
from sandbox import Sandbox
import json


async def stream_output(
    stream, prefix, completion_message=None, completion_future=None
):
    """
    Streams output from the given stream, printing each chunk with the specified prefix.
    If a completion_message is provided, it sets the completion_future when that message is found.
    """
    try:
        async for chunk in stream:
            print(f"[{prefix}] {chunk}", end="", flush=True)
            if completion_message and completion_message in chunk:
                if completion_future and not completion_future.done():
                    completion_future.set_result(True)
    except asyncio.CancelledError:
        pass
    finally:
        if completion_future and not completion_future.done():
            completion_future.set_exception(
                RuntimeError("Stream ended before completion message was found.")
            )


async def start_ollama_webserver(sandbox: Sandbox, model_name: str):
    """
    Installs ollama, starts the ollama server, pulls the specified model, and starts a webserver.
    Returns the process handle.

    Args:
        sandbox (Sandbox): The sandbox instance to run commands in.
        model_name (str): The name of the model to pull using ollama.
    """
    process = await sandbox.exec(
        "bash",
        f"/app/src/scripts/ollama_web_server.sh {model_name}",
    )

    # Create a future to signal when the model pull is complete
    pull_completion_future = asyncio.Future()

    # Start background tasks to stream stdout and stderr
    stdout_task = asyncio.create_task(
        stream_output(
            process.stdout, "STDOUT", "model pull completed", pull_completion_future
        )
    )
    stderr_task = asyncio.create_task(stream_output(process.stderr, "STDERR"))

    # Wait for the model pull to complete
    await pull_completion_future

    return process, [stdout_task, stderr_task]


async def main():
    """
    A simple example demonstrating how to run ollama using the Cloud Run Sandbox Python client.

    This script expects the URL of your deployed Cloud Run service to be
    set in the `CLOUD_RUN_URL` environment variable.

    The WebSocket URL should be in the format: wss://<your-cloud-run-url>.

    Ensure you also installed the Sandbox client for Python before running this.

    Example:
        CLOUD_RUN_URL="wss://sandbox-xxxxxxxxxx-uc.a.run.app" python3 example/python/basic.py
    """
    url = os.environ.get("CLOUD_RUN_URL").replace("https://", "wss://")
    if not url:
        print("Error: Please set the CLOUD_RUN_URL environment variable.")
        print('Example: export CLOUD_RUN_URL="wss://your-service-url.run.app"')
        return

    print(f"Connecting to sandbox at {url}...")

    # Create a secure SSL context using certifi's certificate bundle.
    # This is the recommended approach for ensuring secure connections.
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    io_tasks = []
    try:
        # Create a new sandbox session
        sandbox = await Sandbox.create(
            url,
            ssl=ssl_context,
            enable_debug=True,
            debug_label="ollama_example",
            enable_authentication=True,
        )
        process, io_tasks = await start_ollama_webserver(sandbox, model_name="gemma3")
        # The model is pulled, now we can interact with it.
        await process.write_to_stdin("Hello there!\n")
        # Wait for some time to receive responses.
        await asyncio.sleep(20)

    except Exception as e:
        print(f"\nAn error occurred: {e}")

    finally:
        for task in io_tasks:
            task.cancel()
        await asyncio.gather(*io_tasks, return_exceptions=True)
        # Terminate the sandbox session
        if "sandbox" in locals() and sandbox:
            print("\nTerminating sandbox...")
            await sandbox.kill()
            print("Sandbox terminated.")


if __name__ == "__main__":
    # This script needs the `clients/python` directory to be in the PYTHONPATH
    # You can run it from the root of the repository like this:
    # PYTHONPATH=./clients/python/src python3 example/client_example.py
    asyncio.run(main())
