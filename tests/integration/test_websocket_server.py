import pytest
from fastapi.testclient import TestClient
from src.server import app
import shutil

client = TestClient(app)
runsc_path = shutil.which("runsc")

def test_websocket_attach_not_found():
    """
    Tests attaching to a non-existent sandbox via WebSocket.
    """
    with client.websocket_connect("/attach/non-existent-sandbox") as websocket:
        data = websocket.receive_json()
        assert data == {"event": "status_update", "status": "SANDBOX_NOT_FOUND"}

@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
def test_gvisor_sandbox_creation_and_execution():
    """
    Tests the creation and execution of a gVisor sandbox via the WebSocket interface.
    """
    with client.websocket_connect("/create") as websocket:
        # 1. Send initial config and receive confirmation
        websocket.send_json({"idle_timeout": 120})
        assert websocket.receive_json()["event"] == "status_update"
        assert websocket.receive_json()["event"] == "sandbox_id"
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        # 2. Execute a python command
        websocket.send_json({"language": "python", "code": "print('Hello from gVisor')"})
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello from gVisor\n"}

        # 3. Execute a bash command
        websocket.send_json({"language": "bash", "code": "echo 'Hello again from gVisor'"})
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello again from gVisor\n"}