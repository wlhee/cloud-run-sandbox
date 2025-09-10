import asyncio
import os
import ssl
from codesandbox import Sandbox

async def main():
    """
    A simple example demonstrating how to use the Cloud Run Sandbox Python client.
    
    This script expects the URL of your deployed Cloud Run service to be
    set in the `CLOUD_RUN_URL` environment variable.
    
    The WebSocket URL should be in the format: wss://<your-cloud-run-url>
    
    Example:
        export CLOUD_RUN_URL="wss://sandbox-xxxxxxxxxx-uc.a.run.app"
        python3 example/client_example.py
    """
    url = os.environ.get("CLOUD_RUN_URL")
    if not url:
        print("Error: Please set the CLOUD_RUN_URL environment variable.")
        print("Example: export CLOUD_RUN_URL=\"wss://your-service-url.run.app\"")
        return

    print(f"Connecting to sandbox at {url}...")
    
    # This is a workaround for local SSL certificate verification issues.
    # It is insecure and should NOT be used in production.
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        # Create a new sandbox session
        sandbox = await Sandbox.create(url, ssl=ssl_context)
        print(f"Successfully created sandbox with ID: {sandbox.sandbox_id}")

        # Execute a bash command
        print("\nExecuting command: echo 'Hello from bash!'")
        process = await sandbox.exec("echo 'Hello from bash!'", "bash")

        # Read the output streams
        stdout = await process.stdout.read()
        stderr = await process.stderr.read()
        
        print("\n--- Bash Output ---")
        if stdout:
            print(f"STDOUT:\n{stdout}")
        if stderr:
            print(f"STDERR:\n{stderr}")
        print("-------------------")

        # Execute a python command
        print("\nExecuting command: print('Hello from python!')")
        process = await sandbox.exec("print('Hello from python!')", "python")

        # Read the output streams
        stdout = await process.stdout.read()
        stderr = await process.stderr.read()
        
        print("\n--- Python Output ---")
        if stdout:
            print(f"STDOUT:\n{stdout}")
        if stderr:
            print(f"STDERR:\n{stderr}")
        print("---------------------")

    except Exception as e:
        print(f"\nAn error occurred: {e}")
    
    finally:
        # Terminate the sandbox session
        if 'sandbox' in locals() and sandbox:
            print("\nTerminating sandbox...")
            await sandbox.terminate()
            print("Sandbox terminated.")

if __name__ == "__main__":
    # This script needs the `clients/python` directory to be in the PYTHONPATH
    # You can run it from the root of the repository like this:
    # PYTHONPATH=./clients/python/src python3 example/client_example.py
    asyncio.run(main())
