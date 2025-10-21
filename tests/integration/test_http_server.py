import pytest
from fastapi.testclient import TestClient
from src.server import app
import shutil
from src.handlers import http
from src.sandbox.manager import SandboxManager

# This client is used by the non-gVisor tests
client = TestClient(app)

runsc_path = shutil.which("runsc")

def test_status_endpoint():
    """
    Tests that the /status endpoint returns a 200 OK response.
    """
    response = client.get("/status")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
@pytest.mark.parametrize("language, code, expected_stdout, expected_stderr", [
    ("python", "import sys; print('hello'); print('world', file=sys.stderr)", "hello", "world"),
    ("bash", "echo 'hello from bash'; echo 'error from bash' >&2", "hello from bash", "error from bash"),
])
def test_execute_streaming_gvisor(language, code, expected_stdout, expected_stderr):
    """
    Tests the successful execution of code via the streaming HTTP endpoint using a gVisor sandbox.
    This is an integration test that requires 'runsc' to be in the PATH.
    """
    with TestClient(app) as client:
        response = client.post(f"/execute?language={language}", content=code)
        assert response.status_code == 200
        
        lines = response.text.strip().split('\n')
        
        # The last line is the exit code
        assert lines[-1] == "exit_code: 0"
        
        stdout = "".join([line for line in lines[:-1] if line.startswith("stdout: ")]).replace("stdout: ", "")
        stderr = "".join([line for line in lines[:-1] if line.startswith("stderr: ")]).replace("stderr: ", "")
        
        assert expected_stdout in stdout
        assert expected_stderr in stderr
