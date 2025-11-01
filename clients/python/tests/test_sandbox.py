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
import json
import pytest
import websockets
from unittest.mock import AsyncMock, patch

from sandbox.sandbox import Sandbox
from sandbox.exceptions import SandboxCreationError, SandboxConnectionError, SandboxStateError, SandboxExecutionError, SandboxFilesystemSnapshotError, SandboxCheckpointError
from sandbox.types import MessageKey, EventType, SandboxEvent

@pytest.fixture
def mock_websocket_factory():
    """
    A pytest fixture that provides a factory for creating a mocked websocket.
    It patches `websockets.connect` and allows tests to specify message scripts
    that are sent in response to client actions (like `exec`).
    """
    with patch('sandbox.sandbox.websockets.connect', new_callable=AsyncMock) as mock_connect:
        
        async def _factory(creation_messages, exec_messages_list=None, close_on_finish=True):
            if exec_messages_list is None:
                exec_messages_list = []
                
            mock_ws = AsyncMock()
            mock_connect.return_value = mock_ws
            
            message_queue = asyncio.Queue()
            mock_ws.message_queue = message_queue  # Expose the queue for tests
            exec_called_event = asyncio.Event()

            for msg in creation_messages:
                await message_queue.put(json.dumps(msg))
            
            # For tests that don't call exec, the listener should terminate after creation.
            if not exec_messages_list:
                await message_queue.put(websockets.exceptions.ConnectionClosed(None, None))

            send_count = 0
            async def send_side_effect(message):
                nonlocal send_count
                msg_data = json.loads(message)
                print(f"SEND: {msg_data}")
                
                # Check if this is the exec command by looking for the 'code' key.
                if "code" in msg_data:
                    exec_called_event.set()
                    exec_called_event.clear()
                    
                    exec_messages = exec_messages_list[send_count]
                    send_count += 1
                    
                    for msg in exec_messages:
                        await message_queue.put(json.dumps(msg))
                    
                    # After the last exec, we're done.
                    if send_count == len(exec_messages_list) and close_on_finish:
                        await message_queue.put(websockets.exceptions.ConnectionClosed(None, None))
                elif msg_data.get("action") == "snapshot_filesystem":
                    exec_called_event.set()
                    exec_called_event.clear()
                    
                    exec_messages = exec_messages_list[send_count]
                    send_count += 1
                    
                    for msg in exec_messages:
                        await message_queue.put(json.dumps(msg))
                elif msg_data.get("action") == "checkpoint":
                    exec_called_event.set()
                    exec_called_event.clear()
                    
                    exec_messages = exec_messages_list[send_count]
                    send_count += 1
                    
                    for msg in exec_messages:
                        await message_queue.put(json.dumps(msg))
                else:
                    # This is the idle_timeout message from the Sandbox, do nothing.
                    pass

            mock_ws.send.side_effect = send_side_effect

            async def recv_side_effect():
                print("RECV: waiting for message")
                # If the queue is empty, it means we're in an exec test, waiting for the send() call.
                if message_queue.empty():
                    print("RECV: queue empty, waiting for exec event")
                    await exec_called_event.wait()

                item = await message_queue.get()
                if isinstance(item, Exception):
                    raise item
                print(f"RECV: {item}")
                return item
            mock_ws.recv.side_effect = recv_side_effect
            
            async def wait_for_kill_and_send_sandbox_killed():
                while True:
                    if mock_ws.send.call_args:
                        message = mock_ws.send.call_args[0][0]
                        if json.loads(message).get("action") == "kill_sandbox":
                            await message_queue.put(
                                json.dumps({
                                    MessageKey.EVENT: EventType.STATUS_UPDATE,
                                    MessageKey.STATUS: SandboxEvent.SANDBOX_KILLED
                                })
                            )
                            break
                    await asyncio.sleep(0.01)
            mock_ws.wait_for_kill_and_send_sandbox_killed = wait_for_kill_and_send_sandbox_killed
            
            return mock_ws

        yield _factory

@pytest.mark.asyncio
async def test_sandbox_create_and_kill(mock_websocket_factory):
    """
    Tests that a sandbox can be created and killed without errors.
    This test interacts only with the public API of the Sandbox.
    """
    # Arrange
    # Define the script of messages for a successful creation.
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    # Get a pre-programmed mock websocket from our factory.
    mock_ws = await mock_websocket_factory(creation_messages)

    # Act
    # Create the sandbox. The test passes if this completes without error.
    sandbox = await Sandbox.create("ws://test")
    
    # Assert (Creation)
    # We check the public `sandbox_id` property.
    assert sandbox.sandbox_id == "test_id"
    
    # Act (Termination)
    # Terminate the sandbox. The test passes if this completes without hanging.
    await sandbox.kill(timeout=0.1)

    # Assert (Termination)
    # We verify that the public `close` method of the websocket was called.
    mock_ws.close.assert_awaited_once()

@pytest.mark.asyncio
async def test_sandbox_create_failure(mock_websocket_factory):
    """
    Tests that Sandbox.create raises a SandboxCreationError if the server
    reports a creation failure.
    """
    # Arrange
    error_messages = [
        {
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_CREATION_ERROR,
            MessageKey.MESSAGE: "Failed to create sandbox"
        },
    ]
    await mock_websocket_factory(error_messages)

    # Act & Assert
    with pytest.raises(SandboxCreationError, match="Failed to create sandbox"):
        await Sandbox.create("ws://test")

@pytest.mark.asyncio
async def test_sandbox_connection_lost_during_creation(mock_websocket_factory):
    """
    Tests that a connection lost during creation raises an error.
    """
    # Arrange
    # We provide an empty list of messages, so the ConnectionClosed exception
    # will be raised immediately on the first `recv()` call.
    await mock_websocket_factory([])

    # Act & Assert
    with pytest.raises(SandboxConnectionError, match="Connection closed:"):
        await Sandbox.create("ws://test")

@pytest.mark.asyncio
async def test_sandbox_exec_dispatches_messages(mock_websocket_factory):
    """
    Tests that the sandbox correctly dispatches messages in response to exec.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    exec_messages = [
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING},
        {MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "output"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_DONE},
    ]
    await mock_websocket_factory(creation_messages, [exec_messages])
    
    sandbox = await Sandbox.create("ws://test")
    
    # Act
    process = await sandbox.exec("bash", "command")    
    # Assert
    output = await process.stdout.read_all()
    assert output == "output"
    await process.wait()
    await sandbox.kill(timeout=0.1)

@pytest.mark.asyncio
async def test_can_exec_sequentially(mock_websocket_factory):
    """
    Tests that multiple processes can be executed one after another in the same sandbox.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    exec_messages_1 = [
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING},
        {MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "output1"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_DONE},
    ]
    exec_messages_2 = [
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING},
        {MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "output2"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_DONE},
    ]
    
    await mock_websocket_factory(creation_messages, [exec_messages_1, exec_messages_2])
    
    sandbox = await Sandbox.create("ws://test")

    # Act & Assert for first process
    process1 = await sandbox.exec("command1", "bash")
    output1 = await process1.stdout.read_all()
    assert output1 == "output1"
    await process1.wait()

    # Act & Assert for second process
    process2 = await sandbox.exec("command2", "bash")
    output2 = await process2.stdout.read_all()
    assert output2 == "output2"
    await process2.wait()

    await sandbox.kill(timeout=0.1)

@pytest.mark.asyncio
async def test_cannot_exec_multiple_processes_concurrently(mock_websocket_factory):
    """
    Tests that the sandbox raises an error if exec is called while a process is already running.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    # Note: No EXECUTION_DONE message is sent, so the first process remains active.
    exec_messages = [
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING},
        {MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "output"},
    ]
    
    await mock_websocket_factory(creation_messages, [exec_messages], close_on_finish=False)
    
    sandbox = await Sandbox.create("ws://test")

    # Act & Assert
    # Start the first process. We don't await its completion.
    await sandbox.exec("command1", "bash")
    
    # Try to start a second process while the first is still "running".
    with pytest.raises(RuntimeError, match="Another process is already running"):
        await sandbox.exec("command2", "bash")

    # Cleanup
    await sandbox.kill(timeout=0.1)

@pytest.mark.asyncio
async def test_listen_task_is_cancelled_on_kill(mock_websocket_factory):
    """
    Tests that the internal _listen task is properly awaited and cancelled
    when the sandbox is killed, preventing a resource leak.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    await mock_websocket_factory(creation_messages, close_on_finish=False)

    # Act
    sandbox = await Sandbox.create("ws://test")
    listen_task = sandbox._listen_task # Access internal task for testing

    # Assert (pre-condition)
    assert not listen_task.done()

    # Act
    await sandbox.kill(timeout=0.1)

    # Assert (post-condition)
    assert listen_task.done()

@pytest.mark.asyncio
async def test_exec_raises_error_if_not_running(mock_websocket_factory):
    """
    Tests that exec raises a SandboxStateError if the sandbox is not in the 'running' state.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    await mock_websocket_factory(creation_messages, close_on_finish=False)
    
    sandbox = await Sandbox.create("ws://test")
    await sandbox.kill(timeout=0.1) # Terminate the sandbox to put it in a non-running state.

    # Act & Assert
    with pytest.raises(SandboxStateError, match="Sandbox is not in a running state. Current state: closed"):
        await sandbox.exec("command", "bash")

@pytest.mark.asyncio
async def test_unsupported_language_error_raises_exception(mock_websocket_factory):
    """
    Tests that a SandboxExecutionError is raised for unsupported language errors.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    exec_messages = [
        {
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_UNSUPPORTED_LANGUAGE_ERROR,
            MessageKey.MESSAGE: "Unsupported language: javascript"
        },
    ]
    await mock_websocket_factory(creation_messages, [exec_messages])
    
    sandbox = await Sandbox.create("ws://test")
    
    # Act & Assert
    with pytest.raises(SandboxExecutionError, match="Unsupported language: javascript"):
        await sandbox.exec("javascript", "console.log('hello')")
    
    await sandbox.kill(timeout=0.1)

@pytest.mark.asyncio
async def test_debug_logging(mock_websocket_factory, capsys):
    """
    Tests that debug logs are correctly generated when the feature is enabled
    and suppressed when disabled.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    exec_messages = [
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING},
        {MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "output"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_DONE},
    ]
    
    # --- Test with debug disabled ---
    await mock_websocket_factory(creation_messages, [exec_messages], close_on_finish=False)
    sandbox_no_debug = await Sandbox.create("ws://test", enable_debug=False)
    await sandbox_no_debug.exec("bash", "command")
    await sandbox_no_debug.kill(timeout=0.1)
    
    captured_no_debug = capsys.readouterr()
    assert "[SandboxClient DEBUG|" not in captured_no_debug.out

    # --- Test with debug enabled ---
    await mock_websocket_factory(creation_messages, [exec_messages], close_on_finish=False)
    sandbox_debug = await Sandbox.create("ws://test", enable_debug=True, debug_label="TestLabel")
    process = await sandbox_debug.exec("bash", "command")
    await process.wait()
    await sandbox_debug.kill(timeout=0.1)

    captured_debug = capsys.readouterr()
    
    # Assert that key lifecycle events are logged with the correct label
    assert "[TestLabel] Connecting to ws://test/create" in captured_debug.out
    assert "[TestLabel] Connection established." in captured_debug.out
    assert "[TestLabel] Received message: {\"event\": \"sandbox_id\", \"sandbox_id\": \"test_id\"}" in captured_debug.out
    assert "[TestLabel] Received message: {\"event\": \"status_update\", \"status\": \"SANDBOX_RUNNING\"}" in captured_debug.out
    assert "[TestLabel] Received message: {\"event\": \"status_update\", \"status\": \"SANDBOX_EXECUTION_RUNNING\"}" in captured_debug.out
    
    # Assert that noisy I/O events are NOT logged
    assert "STDOUT" not in captured_debug.out
    assert "STDERR" not in captured_debug.out
    
    assert "[TestLabel] Received message: {\"event\": \"status_update\", \"status\": \"SANDBOX_EXECUTION_DONE\"}" in captured_debug.out
    assert "[TestLabel] Closing WebSocket connection." in captured_debug.out

@pytest.mark.asyncio
async def test_sandbox_attach_success(mock_websocket_factory):
    """
    Tests that a sandbox can be attached to successfully.
    """
    # Arrange
    attach_messages = [
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    mock_ws = await mock_websocket_factory(attach_messages)

    # Act
    sandbox = await Sandbox.attach("ws://test", "existing_id")
    
    # Assert
    assert sandbox.sandbox_id == "existing_id"
    
    await sandbox.kill(timeout=0.1)
    mock_ws.close.assert_awaited_once()

@pytest.mark.asyncio
async def test_sandbox_attach_not_found(mock_websocket_factory):
    """
    Tests that attach raises SandboxCreationError if the sandbox is not found.
    """
    # Arrange
    error_messages = [
        {
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_NOT_FOUND,
            MessageKey.MESSAGE: "Sandbox not found"
        },
    ]
    await mock_websocket_factory(error_messages)

    # Act & Assert
    with pytest.raises(SandboxCreationError, match="Sandbox not found"):
        await Sandbox.attach("ws://test", "non_existent_id")

@pytest.mark.asyncio
async def test_sandbox_attach_in_use(mock_websocket_factory):
    """
    Tests that attach raises SandboxCreationError if the sandbox is in use.
    """
    # Arrange
    error_messages = [
        {
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_IN_USE,
            MessageKey.MESSAGE: "Sandbox in use"
        },
    ]
    await mock_websocket_factory(error_messages)

    # Act & Assert
    with pytest.raises(SandboxCreationError, match="Sandbox in use"):
        await Sandbox.attach("ws://test", "in_use_id")

@pytest.mark.asyncio
async def test_sandbox_connection_lost_during_attach(mock_websocket_factory):
    """
    Tests that a connection lost during attach raises a SandboxConnectionError.
    """
    # Arrange
    await mock_websocket_factory([])

    # Act & Assert
    with pytest.raises(SandboxConnectionError, match="Connection closed:"):
        await Sandbox.attach("ws://test", "any_id")


@pytest.mark.asyncio
async def test_sandbox_kill_sends_kill_action(mock_websocket_factory):
    """
    Tests that calling kill() on a sandbox sends the correct kill_sandbox action.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    mock_ws = await mock_websocket_factory(creation_messages, close_on_finish=False)
    sandbox = await Sandbox.create("ws://test")

    # Act
    await sandbox.kill()

    # Assert
    mock_ws.send.assert_any_call(json.dumps({"action": "kill_sandbox"}))


@pytest.mark.asyncio
async def test_sandbox_kill_unblocks_on_server_messages(mock_websocket_factory):
    """
    Tests that kill() is unblocked when SANDBOX_KILLED and SANDBOX_DELETED messages are received from the server.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    mock_ws = await mock_websocket_factory(creation_messages, close_on_finish=False)
    sandbox = await Sandbox.create("ws://test")

    # Act
    # Use the helper to coordinate the test
    await asyncio.gather(
        sandbox.kill(),
        mock_ws.wait_for_kill_and_send_sandbox_killed()
    )

    # Assert
    assert sandbox._state == "closed"
    mock_ws.send.assert_any_call(json.dumps({"action": "kill_sandbox"}))


@pytest.mark.asyncio
async def test_sandbox_kill_timeout_returns(mock_websocket_factory):
    """
    Tests that kill() returns even if the server does not send a confirmation message,
    relying on the timeout mechanism.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    # Configure mock to NOT send kill confirmation messages
    mock_ws = await mock_websocket_factory(creation_messages, close_on_finish=False)
    sandbox = await Sandbox.create("ws://test")

    # Act
    # Call kill with a short timeout and expect it to complete without server confirmation
    await sandbox.kill(timeout=0.1)

    # Assert
    # The sandbox should transition to 'closed' state due to the timeout
    assert sandbox._state == "closed"
    mock_ws.send.assert_any_call(json.dumps({"action": "kill_sandbox"}))


@pytest.mark.asyncio
async def test_sandbox_kill_is_idempotent(mock_websocket_factory):
    """
    Tests that calling kill() multiple times does not cause errors.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    mock_ws = await mock_websocket_factory(creation_messages, close_on_finish=False)
    sandbox = await Sandbox.create("ws://test")

    # Act
    # Call kill multiple times
    await sandbox.kill()
    await sandbox.kill()

    # Assert
    # The test passes if no exceptions are raised and the state is closed.
    assert sandbox._state == "closed"

@pytest.mark.asyncio
async def test_snapshot_filesystem_raises_error_if_not_running(mock_websocket_factory):
    """
    Tests that snapshot_filesystem raises a SandboxStateError if the sandbox is not in the 'running' state.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    await mock_websocket_factory(creation_messages, close_on_finish=False)
    
    sandbox = await Sandbox.create("ws://test")
    await sandbox.kill(timeout=0.1) # Terminate the sandbox to put it in a non-running state.

    # Act & Assert
    with pytest.raises(SandboxStateError, match="Sandbox is not in a running state. Current state: closed"):
        await sandbox.snapshot_filesystem("test_snapshot")


@pytest.mark.asyncio
async def test_snapshot_filesystem_success(mock_websocket_factory):
    """
    Tests that snapshot_filesystem sends the correct message and waits for the event.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    snapshot_messages = [
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_FILESYSTEM_SNAPSHOT_CREATED},
    ]
    mock_ws = await mock_websocket_factory(creation_messages, [snapshot_messages], close_on_finish=False)
    
    sandbox = await Sandbox.create("ws://test")

    # Act
    await sandbox.snapshot_filesystem("test_snapshot")

    # Assert
    mock_ws.send.assert_any_call(json.dumps({"action": "snapshot_filesystem", "name": "test_snapshot"}))
    assert sandbox._state == "running"
    await sandbox.kill(timeout=0.1)


@pytest.mark.asyncio
async def test_snapshot_filesystem_raises_error_on_failure(mock_websocket_factory):
    """
    Tests that snapshot_filesystem raises a SandboxFilesystemSnapshotError if the server sends a SANDBOX_FILESYSTEM_SNAPSHOT_ERROR event.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    snapshot_messages = [
        {
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_FILESYSTEM_SNAPSHOT_ERROR,
            MessageKey.MESSAGE: "Snapshot failed"
        },
    ]
    await mock_websocket_factory(creation_messages, [snapshot_messages], close_on_finish=False)
    
    sandbox = await Sandbox.create("ws://test")

    # Act & Assert
    with pytest.raises(SandboxFilesystemSnapshotError, match="Snapshot failed"):
        await sandbox.snapshot_filesystem("test_snapshot")
    
    await sandbox.kill(timeout=0.1)


@pytest.mark.asyncio
async def test_create_sends_filesystem_snapshot_name(mock_websocket_factory):
    """
    Tests that create sends the filesystem_snapshot_name parameter.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    mock_ws = await mock_websocket_factory(creation_messages, close_on_finish=False)

    # Act
    sandbox = await Sandbox.create("ws://test", filesystem_snapshot_name="test_snapshot")

    # Assert
    mock_ws.send.assert_any_call(json.dumps({"idle_timeout": 60, "filesystem_snapshot_name": "test_snapshot"}))
    await sandbox.kill(timeout=0.1)


@pytest.mark.asyncio
async def test_create_sends_enable_checkpoint(mock_websocket_factory):
    """
    Tests that create sends the enable_checkpoint parameter.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    mock_ws = await mock_websocket_factory(creation_messages, close_on_finish=False)

    # Act
    sandbox = await Sandbox.create("ws://test", enable_sandbox_checkpoint=True)

    # Assert
    mock_ws.send.assert_any_call(json.dumps({"idle_timeout": 60, "enable_checkpoint": True}))
    await sandbox.kill(timeout=0.1)


@pytest.mark.asyncio
async def test_create_sends_enable_idle_timeout_auto_checkpoint(mock_websocket_factory):
    """
    Tests that create sends the enable_idle_timeout_auto_checkpoint parameter.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    mock_ws = await mock_websocket_factory(creation_messages, close_on_finish=False)

    # Act
    sandbox = await Sandbox.create("ws://test", enable_idle_timeout_auto_checkpoint=True)

    # Assert
    mock_ws.send.assert_any_call(json.dumps({"idle_timeout": 60, "enable_idle_timeout_auto_checkpoint": True}))
    await sandbox.kill(timeout=0.1)


@pytest.mark.asyncio
async def test_checkpoint_raises_error_if_not_running(mock_websocket_factory):
    """
    Tests that checkpoint raises a SandboxStateError if the sandbox is not in the 'running' state.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    await mock_websocket_factory(creation_messages, close_on_finish=False)
    
    sandbox = await Sandbox.create("ws://test")
    await sandbox.kill(timeout=0.1) # Terminate the sandbox to put it in a non-running state.

    # Act & Assert
    with pytest.raises(SandboxStateError, match="Sandbox is not in a running state. Current state: closed"):
        await sandbox.checkpoint()


@pytest.mark.asyncio
async def test_checkpoint_success(mock_websocket_factory):
    """
    Tests that checkpoint sends the correct message, waits for the event,
    and handles the subsequent connection close from the server.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    checkpoint_messages = [
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_CHECKPOINTED},
    ]
    mock_ws = await mock_websocket_factory(creation_messages, [checkpoint_messages], close_on_finish=False)
    
    sandbox = await Sandbox.create("ws://test")

    # Act
    await sandbox.checkpoint()

    # Assert that the checkpoint action was sent
    mock_ws.send.assert_any_call(json.dumps({"action": "checkpoint"}))
    
    # The state should be 'closed' after shutdown is called
    assert sandbox._state == "closed"

    # The listen task should complete because shutdown was called
    await sandbox._listen_task

    # Assert that the websocket was closed
    mock_ws.close.assert_called_once()


@pytest.mark.asyncio
async def test_checkpoint_raises_error_on_failure(mock_websocket_factory):
    """
    Tests that checkpoint raises a SandboxCheckpointError if the server sends a SANDBOX_CHECKPOINT_ERROR event.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    checkpoint_messages = [
        {
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_CHECKPOINT_ERROR,
            MessageKey.MESSAGE: "Checkpoint failed"
        },
    ]
    await mock_websocket_factory(creation_messages, [checkpoint_messages], close_on_finish=False)
    
    sandbox = await Sandbox.create("ws://test")

    # Act & Assert
    with pytest.raises(SandboxCheckpointError, match="Checkpoint failed"):
        await sandbox.checkpoint()
    
    await sandbox.kill(timeout=0.1)


@pytest.mark.asyncio
async def test_checkpoint_raises_error_if_execution_in_progress(mock_websocket_factory):
    """
    Tests that checkpoint raises a SandboxCheckpointError if an execution is in progress.
    """
    # Arrange
    creation_messages = [
        {MessageKey.EVENT: EventType.SANDBOX_ID, MessageKey.SANDBOX_ID: "test_id"},
        {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_RUNNING},
    ]
    checkpoint_messages = [
        {
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_IN_PROGRESS_ERROR,
            MessageKey.MESSAGE: "Execution in progress"
        },
    ]
    await mock_websocket_factory(
        creation_messages,
        [checkpoint_messages],
        close_on_finish=False
    )

    sandbox = await Sandbox.create("ws://test")

    # Act & Assert
    with pytest.raises(SandboxCheckpointError, match="Execution in progress"):
        print("TEST: awaiting sandbox.checkpoint")
        await sandbox.checkpoint()
        print("TEST: sandbox.checkpoint returned")

    # The state should be back to running
    assert sandbox._state == "running"

    await sandbox.kill(timeout=0.1)


