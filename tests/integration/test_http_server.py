import pytest
from fastapi.testclient import TestClient
from src.server import app
import shutil

client = TestClient(app)

# Check if 'runsc' is in the PATH
runsc_path = shutil.which("runsc")

def test_status_endpoint():
    """Tests the GET /status endpoint."""
    response = client.get("/status")
    assert response.status_code == 200
    assert response.text == "Server is running"

@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
@pytest.mark.parametrize("language, code, expected_stdout, expected_stderr", [
    ("python", "import sys; print('hello'); print('world', file=sys.stderr)", "hello", "world"),
    ("bash", "echo 'hello from bash'; echo 'error from bash' >&2", "hello from bash", "error from bash"),
])
def test_execute_streaming_gvisor(language, code, expected_stdout, expected_stderr):
    """
    Tests the POST /execute endpoint with a real gVisor sandbox for different languages.
    """
    # Act
    response = client.post(
        f"/execute?language={language}",
        content=code,
        headers={"Content-Type": "text/plain"}
    )

    # Assert
    assert response.status_code == 200
    assert expected_stdout in response.text
    assert expected_stderr in response.text
