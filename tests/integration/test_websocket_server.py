import pytest
from fastapi.testclient import TestClient
from src.server import app
import shutil
import asyncio
from starlette.websockets import WebSocketDisconnect

client = TestClient(app)
runsc_path = shutil.which("runsc")

def test_websocket_attach_not_found():
    """
    Tests attaching to a non-existent sandbox via WebSocket.
    """
    with client.websocket_connect("/attach/non-existent-sandbox") as websocket:
        data = websocket.receive_json()
        assert data == {"event": "status_update", "status": "SANDBOX_NOT_FOUND"}

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_creation_and_execution():
    """
    Tests the creation and execution of a gVisor sandbox via the WebSocket interface.
    """
    with client.websocket_connect("/create") as websocket:
        # 1. Send initial config and receive confirmation
        print(">>> [TEST] Sending initial config")
        websocket.send_json({"idle_timeout": 120})
        
        print(">>> [TEST] Receiving status_update")
        assert websocket.receive_json()["event"] == "status_update"
        print(">>> [TEST] Receiving sandbox_id")
        assert websocket.receive_json()["event"] == "sandbox_id"
        print(">>> [TEST] Receiving SANDBOX_RUNNING")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}
        print(">>> [TEST] Sandbox is running")

        # 2. Execute a python command
        print(">>> [TEST] Sending python code")
        websocket.send_json({"language": "python", "code": "print('Hello from gVisor')"})
        
        print(">>> [TEST] Receiving SANDBOX_EXECUTION_RUNNING")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        print(">>> [TEST] Receiving stdout")
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello from gVisor\n"}
        print(">>> [TEST] Receiving SANDBOX_EXECUTION_DONE")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}
        print(">>> [TEST] Python execution done")

        # 3. Execute a bash command
        print(">>> [TEST] Sending bash code")
        websocket.send_json({"language": "bash", "code": "echo 'Hello again from gVisor'"})
        
        print(">>> [TEST] Receiving SANDBOX_EXECUTION_RUNNING")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        print(">>> [TEST] Receiving stdout")
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello again from gVisor\n"}
        print(">>> [TEST] Receiving SANDBOX_EXECUTION_DONE")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}
        print(">>> [TEST] Bash execution done")

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_execution_error_exit():
    """
    Tests that the websocket connection remains open after a failed execution.
    """
    with client.websocket_connect("/create") as websocket:
        # 1. Send initial config and receive confirmation
        print(">>> [TEST] Sending initial config")
        websocket.send_json({"idle_timeout": 120})
        
        print(">>> [TEST] Receiving status_update")
        assert websocket.receive_json()["event"] == "status_update"
        print(">>> [TEST] Receiving sandbox_id")
        assert websocket.receive_json()["event"] == "sandbox_id"
        print(">>> [TEST] Receiving SANDBOX_RUNNING")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}
        print(">>> [TEST] Sandbox is running")

        # 2. Execute a command that exits with an error
        print(">>> [TEST] Sending bash code with error")
        websocket.send_json({"language": "bash", "code": "echo 'error' >&2; exit 1"})
        
        print(">>> [TEST] Receiving SANDBOX_EXECUTION_RUNNING")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        print(">>> [TEST] Receiving stderr")
        assert websocket.receive_json() == {"event": "stderr", "data": "error\n"}
        print(">>> [TEST] Receiving SANDBOX_EXECUTION_DONE")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}
        print(">>> [TEST] Errored execution done")

        # 3. The connection should remain open for another command
        print(">>> [TEST] Sending second bash command")
        websocket.send_json({"language": "bash", "code": "echo 'still alive'"})
        
        print(">>> [TEST] Receiving SANDBOX_EXECUTION_RUNNING")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        print(">>> [TEST] Receiving stdout")
        assert websocket.receive_json() == {"event": "stdout", "data": "still alive\n"}
        print(">>> [TEST] Receiving SANDBOX_EXECUTION_DONE")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}
        print(">>> [TEST] Second execution done")

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_reject_simultaneous_execution():
    """
    Tests that the server rejects a new execution if one is already running.
    """
    with client.websocket_connect("/create") as websocket:
        # 1. Send initial config and receive confirmation
        print(">>> [TEST] Sending initial config")
        websocket.send_json({"idle_timeout": 120})
        
        print(">>> [TEST] Receiving status_update")
        assert websocket.receive_json()["event"] == "status_update"
        print(">>> [TEST] Receiving sandbox_id")
        assert websocket.receive_json()["event"] == "sandbox_id"
        print(">>> [TEST] Receiving SANDBOX_RUNNING")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}
        print(">>> [TEST] Sandbox is running")

        # 2. Start a long-running command
        print(">>> [TEST] Sending long-running command")
        websocket.send_json({"language": "bash", "code": "sleep 0.2; echo 'done'"})
        
        print(">>> [TEST] Receiving SANDBOX_EXECUTION_RUNNING")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        print(">>> [TEST] Long-running command is running")

        # 3. Try to start another execution while the first is running
        print(">>> [TEST] Sending second command to trigger error")
        websocket.send_json({"language": "python", "code": "print('should fail')"})

        # 4. Assert that the server sends an error message
        print(">>> [TEST] Receiving SANDBOX_EXECUTION_ERROR")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_ERROR"}
        print(">>> [TEST] Receiving error message")
        error_message = websocket.receive_json()
        assert error_message["event"] == "error"
        assert "An execution is already in progress" in error_message["message"]
        print(">>> [TEST] Error message received")
        
        # 5. Wait for the first command to finish and receive its output
        print(">>> [TEST] Receiving stdout from first command")
        assert websocket.receive_json() == {"event": "stdout", "data": "done\n"}
        print(">>> [TEST] Receiving SANDBOX_EXECUTION_DONE from first command")
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}
        print(">>> [TEST] First command finished")
