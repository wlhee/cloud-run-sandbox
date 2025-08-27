import pytest
import subprocess
import time
import os
import tempfile
from pathlib import Path
import requests
import signal
from unittest.mock import patch, AsyncMock
from src.server import lifespan, app
import asyncio

def test_server_sigterm_shutdown_deletes_sandboxes():
    """
    Tests that sending a SIGTERM to the server correctly triggers the
    lifespan shutdown hook and calls the sandbox manager to delete all
    running sandboxes. This is a full end-to-end integration test.
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
    env["PORT"] = "8001"

    server_process = None
    try:
        # 4. Start the server using the correct entrypoint.
        server_process = subprocess.Popen(
            ["python3", "main.py"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 5. Poll the server to wait for it to start up.
        start_time = time.time()
        while time.time() - start_time < 10: # 10-second timeout
            try:
                response = requests.get("http://127.0.0.1:8001/")
                if response.status_code == 200:
                    break
            except requests.ConnectionError:
                time.sleep(0.1) # Wait a bit before retrying
        else:
            pytest.fail("Server did not start within 10 seconds.")

        # 6. Send the SIGTERM signal directly to the server process.
        os.kill(server_process.pid, signal.SIGTERM)

        # 7. Wait for the process to exit gracefully.
        stdout, stderr = server_process.communicate(timeout=10)

        # 8. Assert that the signal file was created.
        assert Path(signal_file_path).exists(), f"Shutdown signal file was not created. Server stderr: {stderr.decode()}"

    finally:
        # 9. Clean up the signal file and ensure the process is terminated.
        if server_process and server_process.poll() is None:
            server_process.kill()
        if os.path.exists(signal_file_path):
            os.remove(signal_file_path)

@pytest.mark.asyncio
@patch('src.server.sandbox_manager.delete_all_sandboxes', new_callable=AsyncMock)
async def test_lifespan_shutdown_hook(mock_delete_all):
    """
    Directly tests that the lifespan shutdown hook correctly calls the sandbox
    manager. This verifies the application logic without a full server process.
    """
    # We need to mock the signal handler registration because it will fail
    # when not run in the main thread. We are testing the shutdown logic here,
    # not the signal handling itself.
    with patch('asyncio.get_event_loop') as mock_get_loop:
        mock_loop = asyncio.get_event_loop()
        mock_loop.add_signal_handler = lambda *args, **kwargs: None
        mock_get_loop.return_value = mock_loop

        async with lifespan(app):
            # Simulate the app running
            mock_delete_all.assert_not_awaited()

    # When the context exits, the shutdown hook should be called.
    mock_delete_all.assert_awaited_once()
