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
from unittest.mock import AsyncMock, MagicMock

from sandbox.process import SandboxProcess, SandboxExecutionError
from sandbox.types import MessageKey, EventType, SandboxEvent

@pytest.mark.asyncio
async def test_process_exec_success_read():
    """
    Tests that a process starts successfully and can read stdout/stderr
    using the .read_all() method.
    """
    # Arrange
    mock_ws = AsyncMock()
    process = SandboxProcess(mock_ws)
    
    async def exec_and_feed_messages():
        # These messages simulate the lifecycle of a successful execution
        messages = [
            {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING},
            {MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "Hello "},
            {MessageKey.EVENT: EventType.STDERR, MessageKey.DATA: "Error "},
            {MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "World"},
            {MessageKey.EVENT: EventType.STDERR, MessageKey.DATA: "Message"},
            {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_DONE},
        ]
        
        # Start exec in the background
        exec_task = asyncio.create_task(process.exec("bash", "echo 'Hello World'"))
        
        # Feed messages to the process to unblock exec and subsequent reads
        for msg in messages:
            process.handle_message(msg)
            await asyncio.sleep(0) # Yield control to allow tasks to run
        
        await exec_task

    # Act
    await exec_and_feed_messages()
    
    stdout = await process.stdout.read_all()
    stderr = await process.stderr.read_all()
    await process.wait()

    # Assert
    assert stdout == "Hello World"
    assert stderr == "Error Message"
    mock_ws.send.assert_called_once()

@pytest.mark.asyncio
async def test_process_stream_iteration():
    """
    Tests that stdout/stderr can be read chunk by chunk using async iteration.
    """
    # Arrange
    mock_ws = AsyncMock()
    process = SandboxProcess(mock_ws)
    
    async def exec_and_feed_messages():
        messages = [
            {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING},
            {MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "Chunk 1"},
            {MessageKey.EVENT: EventType.STDERR, MessageKey.DATA: "Error 1"},
            {MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "Chunk 2"},
            {MessageKey.EVENT: EventType.STDERR, MessageKey.DATA: "Error 2"},
            {MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_DONE},
        ]
        
        exec_task = asyncio.create_task(process.exec("bash", "some command"))
        
        for msg in messages:
            process.handle_message(msg)
            await asyncio.sleep(0)
        
        await exec_task

    # Act
    await exec_and_feed_messages()
    
    stdout_chunks = []
    stderr_chunks = []
    
    async def read_streams():
        async for chunk in process.stdout:
            stdout_chunks.append(chunk)
        async for chunk in process.stderr:
            stderr_chunks.append(chunk)
            
    await asyncio.gather(read_streams(), process.wait())

    # Assert
    assert stdout_chunks == ["Chunk 1", "Chunk 2"]
    assert stderr_chunks == ["Error 1", "Error 2"]

@pytest.mark.asyncio
async def test_process_exec_failure_unblocks_wait():
    """
    Tests that exec raises an exception and that .wait() is unblocked
    if the server reports an execution error.
    """
    # Arrange
    mock_ws = AsyncMock()
    on_done_callback = MagicMock()
    process = SandboxProcess(mock_ws, on_done=on_done_callback)
    
    error_message = {
        MessageKey.EVENT: EventType.STATUS_UPDATE,
        MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_ERROR,
        MessageKey.MESSAGE: "Something went wrong"
    }

    # Act & Assert
    with pytest.raises(SandboxExecutionError, match="Something went wrong"):
        exec_task = asyncio.create_task(process.exec("python", "some code"))
        process.handle_message(error_message)
        await exec_task
    
    # The .wait() call should now complete immediately.
    await asyncio.wait_for(process.wait(), timeout=0.1)
    
    # The on_done callback should have been called.
    on_done_callback.assert_called_once()

@pytest.mark.asyncio
async def test_process_terminate():
    """
    Tests that terminating a process correctly closes the streams.
    """
    # Arrange
    mock_ws = AsyncMock()
    process = SandboxProcess(mock_ws)
    
    async def exec_and_feed_partial():
        # Simulate the start of execution
        process.handle_message({
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING
        })
        await asyncio.sleep(0)
        
        # Simulate some output
        process.handle_message({
            MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "Partial output"
        })
        await asyncio.sleep(0)

    # Act
    exec_task = asyncio.create_task(process.exec("bash", "long command"))
    await exec_and_feed_partial()
    await exec_task # exec() is now unblocked
    
    # Confirm we received the first chunk of output
    first_chunk = await asyncio.wait_for(process.stdout.__aiter__().__anext__(), timeout=0.1)
    assert first_chunk == "Partial output"
    
    # Terminate the process while it's "running"
    await process.terminate()

    # Assert
    # The wait() should resolve immediately because terminate is synchronous
    await asyncio.wait_for(process.wait(), timeout=0.1)
    
    # The streams should be closed, and subsequent reads should yield no more content
    stdout = await process.stdout.read_all()
    assert stdout == ""

@pytest.mark.asyncio
async def test_process_terminate_while_reading():
    """
    Tests that a reader iterating a stream is unblocked gracefully when
    the process is terminated.
    """
    # Arrange
    mock_ws = AsyncMock()
    process = SandboxProcess(mock_ws)
    
    async def exec_and_feed_first_chunk():
        process.handle_message({
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING
        })
        await asyncio.sleep(0)
        process.handle_message({
            MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "First chunk"
        })
        await asyncio.sleep(0)

    exec_task = asyncio.create_task(process.exec("bash", "long command"))
    await exec_and_feed_first_chunk()
    await exec_task

    # Act
    output_chunks = []
    first_chunk_received = asyncio.Event()
    
    async def reader():
        async for chunk in process.stdout:
            output_chunks.append(chunk)
            first_chunk_received.set()
            
    reader_task = asyncio.create_task(reader())
    
    # Wait for the reader to confirm it has processed the first chunk
    await asyncio.wait_for(first_chunk_received.wait(), timeout=0.1)
    
    # Terminate the process while the reader is blocked on the stream
    await process.terminate()

    # Assert
    # The reader task should complete without error
    await asyncio.wait_for(reader_task, timeout=0.1)
    
    # The process should also report as done
    await asyncio.wait_for(process.wait(), timeout=0.1)
    
    # The reader should have received the partial output
    assert output_chunks == ["First chunk"]

@pytest.mark.asyncio
async def test_process_terminate_while_full_reading():
    """
    Tests that a reader calling .read_all() is unblocked gracefully when
    the process is terminated.
    """
    # Arrange
    mock_ws = AsyncMock()
    process = SandboxProcess(mock_ws)
    
    async def exec_and_feed_first_chunk():
        process.handle_message({
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING
        })
        await asyncio.sleep(0)
        process.handle_message({
            MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "First chunk"
        })
        await asyncio.sleep(0)

    exec_task = asyncio.create_task(process.exec("bash", "long command"))
    await exec_and_feed_first_chunk()
    await exec_task

    # Act
    # Start the .read_all() in the background
    reader_task = asyncio.create_task(process.stdout.read_all())
    
    # Give the reader a moment to start and consume the first chunk
    await asyncio.sleep(0.01)
    
    # Terminate the process while the reader is blocked
    await process.terminate()

    # Assert
    # The reader task should complete and return the partial content
    result = await asyncio.wait_for(reader_task, timeout=0.1)
    assert result == "First chunk"
    
    # The process should also report as done
    await asyncio.wait_for(process.wait(), timeout=0.1)

@pytest.mark.asyncio
async def test_wait_is_unblocked_by_done_message():
    """
    Tests that a coroutine awaiting process.wait() is unblocked when the
    'EXECUTION_DONE' message is received.
    """
    # Arrange
    mock_ws = AsyncMock()
    process = SandboxProcess(mock_ws)

    # Act
    wait_task = asyncio.create_task(process.wait())
    
    # Give the task a moment to start waiting
    await asyncio.sleep(0)
    assert not wait_task.done(), "wait() should be blocked before the DONE message"
    
    process.handle_message({
        MessageKey.EVENT: EventType.STATUS_UPDATE,
        MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_DONE
    })

    # Assert
    await asyncio.wait_for(wait_task, timeout=0.1)
    assert wait_task.done(), "wait() should be unblocked after the DONE message"

@pytest.mark.asyncio
async def test_multiple_waits_are_unblocked():
    """
    Tests that multiple coroutines awaiting process.wait() are all unblocked.
    """
    # Arrange
    mock_ws = AsyncMock()
    process = SandboxProcess(mock_ws)

    # Act
    wait_tasks = [asyncio.create_task(process.wait()) for _ in range(3)]
    
    await asyncio.sleep(0)
    assert not any(t.done() for t in wait_tasks)
    
    await process.terminate()

    # Assert
    await asyncio.wait_for(asyncio.gather(*wait_tasks), timeout=0.1)
    assert all(t.done() for t in wait_tasks)

@pytest.mark.asyncio
async def test_terminate_is_idempotent():
    """
    Tests that calling terminate() multiple times does not cause errors.
    """
    # Arrange
    mock_ws = AsyncMock()
    on_done_callback = MagicMock()
    process = SandboxProcess(mock_ws, on_done=on_done_callback)

    # Act
    await process.terminate()
    await process.terminate()

    # Assert
    await process.wait()
    on_done_callback.assert_called_once()

@pytest.mark.asyncio
async def test_process_write_to_stdin():
    """
    Tests that write_to_stdin sends the correct message to the websocket.
    """
    # Arrange
    mock_ws = AsyncMock()
    process = SandboxProcess(mock_ws)
    
    async def exec_and_write():
        # Start exec in the background
        exec_task = asyncio.create_task(process.exec("bash", "cat"))
        
        # Simulate server acknowledging the execution start
        process.handle_message({
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING
        })
        await exec_task
        
        # Write to stdin
        await process.write_to_stdin("hello\n")
        
        # Simulate stdout and done
        process.handle_message({MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "hello\n"})
        process.handle_message({
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_DONE
        })

    # Act
    exec_and_write_task = asyncio.create_task(exec_and_write())
    
    # Read stdout
    stdout = await process.stdout.read_all()
    await process.wait()
    await exec_and_write_task

    # Assert
    assert stdout == "hello\n"
    assert mock_ws.send.call_count == 2
    mock_ws.send.assert_any_call(json.dumps({"language": "bash", "code": "cat"}))
    mock_ws.send.assert_any_call(json.dumps({"event": "stdin", "data": "hello\n"}))