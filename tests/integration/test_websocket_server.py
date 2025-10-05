import pytest
from fastapi.testclient import TestClient
from src.server import app
import shutil
import asyncio
from starlette.websockets import WebSocketDisconnect
import os
import tempfile
from src.sandbox.manager import manager as sandbox_manager

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
        websocket.send_json({"idle_timeout": 120})
        assert websocket.receive_json()["event"] == "status_update"
        assert websocket.receive_json()["event"] == "sandbox_id"
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        # 2. Execute a python command
        websocket.send_json({"language": "python", "code": "print('Hello from gVisor')"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello from gVisor\n"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

        # 3. Execute a bash command
        websocket.send_json({"language": "bash", "code": "echo 'Hello again from gVisor'"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello again from gVisor\n"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_attach_and_execution():
    """
    Tests that a client can attach to an existing sandbox and execute commands.
    """
    # 1. Create a sandbox and get its ID
    with client.websocket_connect("/create") as websocket:
        websocket.send_json({"idle_timeout": 120})
        assert websocket.receive_json()["event"] == "status_update"
        sandbox_id_event = websocket.receive_json()
        assert sandbox_id_event["event"] == "sandbox_id"
        sandbox_id = sandbox_id_event["sandbox_id"]
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

    # 2. Attach to the sandbox in a new session
    with client.websocket_connect(f"/attach/{sandbox_id}") as websocket:
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        # 3. Execute a command in the attached session
        websocket.send_json({"language": "python", "code": "print('Hello from attached session')"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello from attached session\n"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_concurrent_attach_fails():
    """
    Tests that a second client's attempt to attach to an active sandbox fails.
    """
    # 1. Client A creates a sandbox
    with client.websocket_connect("/create") as ws_a:
        ws_a.send_json({"idle_timeout": 120})
        assert ws_a.receive_json()["event"] == "status_update"
        sandbox_id = ws_a.receive_json()["sandbox_id"]
        assert ws_a.receive_json()["status"] == "SANDBOX_RUNNING"

        # 2. Client B attempts to attach to the same sandbox
        with client.websocket_connect(f"/attach/{sandbox_id}") as ws_b:
            assert ws_b.receive_json() == {"event": "status_update", "status": "SANDBOX_IN_USE"}
        
        # 3. Client A can still execute a command
        ws_a.send_json({"language": "python", "code": "print('hello from client A')"})
        assert ws_a.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        assert ws_a.receive_json() == {"event": "stdout", "data": "hello from client A\n"}
        assert ws_a.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_execution_error_exit():
    """
    Tests that the websocket connection remains open after a failed execution.
    """
    with client.websocket_connect("/create") as websocket:
        # 1. Send initial config and receive confirmation
        websocket.send_json({"idle_timeout": 120})
        assert websocket.receive_json()["event"] == "status_update"
        assert websocket.receive_json()["event"] == "sandbox_id"
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        # 2. Execute a command that exits with an error
        websocket.send_json({"language": "bash", "code": "echo 'error' >&2; exit 1"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        assert websocket.receive_json() == {"event": "stderr", "data": "error\n"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

        # 3. The connection should remain open for another command
        websocket.send_json({"language": "bash", "code": "echo 'still alive'"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
        assert websocket.receive_json() == {"event": "stdout", "data": "still alive\n"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_reject_simultaneous_execution():
    """
    Tests that the server rejects a new execution if one is already running.
    """
    with client.websocket_connect("/create") as websocket:
        # 1. Send initial config and receive confirmation
        websocket.send_json({"idle_timeout": 120})
        assert websocket.receive_json()["event"] == "status_update"
        assert websocket.receive_json()["event"] == "sandbox_id"
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        # 2. Start a long-running command
        websocket.send_json({"language": "bash", "code": "sleep 0.2; echo 'done'"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}

        # 3. Try to start another execution while the first is running
        websocket.send_json({"language": "python", "code": "print('should fail')"})

        # 4. Assert that the server sends an error message
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_ERROR"}
        error_message = websocket.receive_json()
        assert error_message["event"] == "error"
        assert "An execution is already in progress" in error_message["message"]
        
        # 5. Wait for the first command to finish and receive its output
        assert websocket.receive_json() == {"event": "stdout", "data": "done\n"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_stdin():
    """
    Tests sending stdin to a running process via the WebSocket interface.
    """
    with client.websocket_connect("/create") as websocket:
        # 1. Send initial config and receive confirmation
        websocket.send_json({"idle_timeout": 120})
        assert websocket.receive_json()["event"] == "status_update"
        assert websocket.receive_json()["event"] == "sandbox_id"
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

        # 2. Execute a python command that reads from stdin
        websocket.send_json({"language": "python", "code": "name = input(); print(f'Hello, {name}')"})
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}

        # 3. Send stdin to the process
        websocket.send_json({"event": "stdin", "data": "World\n"})

        # 4. Verify the output
        assert websocket.receive_json() == {"event": "stdout", "data": "Hello, World\n"}
        assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_websocket_checkpoint_and_restore_success(monkeypatch):
    """
    Tests the full checkpoint and restore lifecycle via WebSocket.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        monkeypatch.setattr(sandbox_manager, "checkpoint_and_restore_path", temp_dir)
        # 1. Create a sandbox with checkpointing enabled
        with client.websocket_connect("/create") as websocket:
            websocket.send_json({"idle_timeout": 120, "enable_checkpoint": True})
            assert websocket.receive_json()["event"] == "status_update"
            sandbox_id = websocket.receive_json()["sandbox_id"]
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

            # 2. Execute a command to create a file
            websocket.send_json({"language": "bash", "code": "echo 'hello' > /test.txt"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

            # 3. Checkpoint the sandbox
            websocket.send_json({"action": "checkpoint"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINTING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINTED"}

        # 4. Attach to the sandbox, which should trigger a restore
        with client.websocket_connect(f"/attach/{sandbox_id}") as websocket:
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RESTORING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

            # 5. Verify the file exists
            websocket.send_json({"language": "bash", "code": "cat /test.txt"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
            assert websocket.receive_json() == {"event": "stdout", "data": "hello\n"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_websocket_multi_checkpoint_and_restore(monkeypatch):
    """
    Tests the full lifecycle of checkpoint -> restore -> checkpoint -> restore.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        monkeypatch.setattr(sandbox_manager, "checkpoint_and_restore_path", temp_dir)
        
        # 1. Create a sandbox with checkpointing enabled
        with client.websocket_connect("/create") as websocket:
            websocket.send_json({"idle_timeout": 120, "enable_checkpoint": True})
            assert websocket.receive_json()["event"] == "status_update"
            sandbox_id = websocket.receive_json()["sandbox_id"]
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

            # 2. Create a file with initial state
            websocket.send_json({"language": "bash", "code": "echo 'state1' > /data.txt"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

            # 3. First checkpoint
            websocket.send_json({"action": "checkpoint"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINTING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINTED"}

        # 4. First restore and verify
        with client.websocket_connect(f"/attach/{sandbox_id}") as websocket:
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RESTORING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}
            websocket.send_json({"language": "bash", "code": "cat /data.txt"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
            assert websocket.receive_json() == {"event": "stdout", "data": "state1\n"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

            # 5. Update the file to a new state
            websocket.send_json({"language": "bash", "code": "echo 'state2' > /data.txt"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

            # 6. Second checkpoint
            websocket.send_json({"action": "checkpoint"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINTING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINTED"}

        # 7. Second restore and verify
        with client.websocket_connect(f"/attach/{sandbox_id}") as websocket:
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RESTORING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}
            websocket.send_json({"language": "bash", "code": "cat /data.txt"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
            assert websocket.receive_json() == {"event": "stdout", "data": "state2\n"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

@pytest.mark.asyncio
@pytest.mark.skip(reason="runsc does not yet support creating from a tarball.")
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_websocket_filesystem_snapshot_and_create(monkeypatch):
    """
    Tests the full filesystem snapshot and create from snapshot lifecycle via WebSocket.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        monkeypatch.setattr(sandbox_manager, "filesystem_snapshot_path", temp_dir)
        # 1. Create a sandbox
        with client.websocket_connect("/create") as websocket:
            websocket.send_json({"idle_timeout": 120})
            assert websocket.receive_json()["event"] == "status_update"
            sandbox_id = websocket.receive_json()["sandbox_id"]
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

            # 2. Execute a command to create a file
            websocket.send_json({"language": "bash", "code": "echo 'hello' > /test.txt"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

            # 3. Snapshot the sandbox
            snapshot_name = "my-snapshot"
            websocket.send_json({"action": "snapshot_filesystem", "name": snapshot_name})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_FILESYSTEM_SNAPSHOT_CREATING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_FILESYSTEM_SNAPSHOT_CREATED"}

        # 4. Create a new sandbox from the snapshot
        with client.websocket_connect("/create") as websocket:
            websocket.send_json({"filesystem_snapshot_name": snapshot_name})
            assert websocket.receive_json()["event"] == "status_update"
            assert websocket.receive_json()["event"] == "sandbox_id"
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

            # 5. Verify the file exists
            websocket.send_json({"language": "bash", "code": "cat /test.txt"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}
            assert websocket.receive_json() == {"event": "stdout", "data": "hello\n"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}

@pytest.mark.asyncio
@pytest.mark.skip(reason="runsc does not yet support creating from a tarball.")
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_websocket_create_from_filesystem_snapshot_not_found(monkeypatch):
    """
    Tests that creating a sandbox from a non-existent snapshot fails.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        monkeypatch.setattr(sandbox_manager, "filesystem_snapshot_path", temp_dir)
        with client.websocket_connect("/create") as websocket:
            websocket.send_json({"filesystem_snapshot_name": "non-existent-snapshot"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CREATION_ERROR"}
            error_message = websocket.receive_json()
            assert error_message["event"] == "error"
            assert "No such file or directory" in error_message["message"]
            with pytest.raises(WebSocketDisconnect) as e:
                websocket.receive_json()
            assert e.value.code == 4000

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_websocket_restore_failure(monkeypatch):
    """
    Tests that a failure during restore is handled gracefully.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        monkeypatch.setattr(sandbox_manager, "checkpoint_and_restore_path", temp_dir)
        # 1. Create and checkpoint a sandbox
        with client.websocket_connect("/create") as websocket:
            websocket.send_json({"idle_timeout": 120, "enable_checkpoint": True})
            assert websocket.receive_json()["event"] == "status_update"
            sandbox_id = websocket.receive_json()["sandbox_id"]
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}
            websocket.send_json({"action": "checkpoint"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINTING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINTED"}

        # 2. Corrupt the checkpoint by deleting the file pointed to by 'latest'
        checkpoints_dir = os.path.join(temp_dir, sandbox_id, "checkpoints")
        latest_path = os.path.join(checkpoints_dir, "latest")
        with open(latest_path, "r") as f:
            latest_checkpoint_name = f.read().strip()
        os.remove(os.path.join(checkpoints_dir, latest_checkpoint_name))

        # 3. Attempt to attach to the sandbox
        with client.websocket_connect(f"/attach/{sandbox_id}") as websocket:
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RESTORING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_NOT_FOUND"}
            with pytest.raises(WebSocketDisconnect) as e:
                websocket.receive_json()
            assert e.value.code == 1011

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_websocket_checkpoint_during_execution(monkeypatch):
    """
    Tests that checkpointing during an execution fails gracefully.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        monkeypatch.setattr(sandbox_manager, "checkpoint_and_restore_path", temp_dir)
        with client.websocket_connect("/create") as websocket:
            # 1. Send initial config and receive confirmation
            websocket.send_json({"idle_timeout": 120, "enable_checkpoint": True})
            assert websocket.receive_json()["event"] == "status_update"
            sandbox_id = websocket.receive_json()["sandbox_id"]
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_RUNNING"}

            # 2. Start a long-running command
            websocket.send_json({"language": "bash", "code": "sleep 2; echo 'done'"})
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_RUNNING"}

            # 3. Try to checkpoint while the first is running
            websocket.send_json({"action": "checkpoint"})

            # 4. Assert that the server sends an error message
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_CHECKPOINTING"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_IN_PROGRESS_ERROR"}
            error_message = websocket.receive_json()
            assert error_message["event"] == "error"
            assert "Cannot checkpoint while an execution is in progress" in error_message["message"]
            
            # 5. Wait for the first command to finish and receive its output
            assert websocket.receive_json() == {"event": "stdout", "data": "done\n"}
            assert websocket.receive_json() == {"event": "status_update", "status": "SANDBOX_EXECUTION_DONE"}
