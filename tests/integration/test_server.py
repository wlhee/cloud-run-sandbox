import pytest
import subprocess
import time
import os
import tempfile
from pathlib import Path

def test_server_shutdown_deletes_sandboxes():
    """
    Tests that sending a SIGTERM to the server correctly triggers the
    lifespan shutdown hook and calls the sandbox manager to delete all
    running sandboxes.
    """
    # 1. Create a temporary file to act as a signal.
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        signal_file_path = tmp.name
    
    # 2. Ensure the file does not exist before the test.
    if os.path.exists(signal_file_path):
        os.remove(signal_file_path)

    # 3. Set the environment variable for the subprocess.
    env = os.environ.copy()
    env["SHUTDOWN_TEST_FILE"] = signal_file_path

    try:
        # 4. Start the server as a subprocess.
        # We use python -m uvicorn to ensure it's run as a module.
        server_process = subprocess.Popen(
            ["python3", "-m", "uvicorn", "src.server:app", "--forwarded-allow-ips='*'", "--proxy-headers"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 5. Wait for the server to start up.
        time.sleep(1)

        # 6. Send the SIGTERM signal.
        server_process.terminate()

        # 7. Wait for the process to exit gracefully.
        server_process.wait(timeout=5)

        # 8. Assert that the signal file was created.
        assert Path(signal_file_path).exists(), "Shutdown signal file was not created."

    finally:
        # 9. Clean up the signal file.
        if os.path.exists(signal_file_path):
            os.remove(signal_file_path)
