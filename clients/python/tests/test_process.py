import asyncio
import json
import pytest
import websockets
from unittest.mock import AsyncMock

from codesandbox.process import SandboxProcess, SandboxExecutionError, SandboxConnectionError
from codesandbox.types import MessageKey, EventType, SandboxEvent

@pytest.mark.asyncio
async def test_process_exec_success_read():
    """
    Tests that a process starts successfully and can read stdout/stderr
    using the .read_all() method.
    """
    # Arrange
    mock_ws = AsyncMock()
    messages = [
        json.dumps({MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING}),
        json.dumps({MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "Hello "}),
        json.dumps({MessageKey.EVENT: EventType.STDERR, MessageKey.DATA: "Error "}),
        json.dumps({MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "World"}),
        json.dumps({MessageKey.EVENT: EventType.STDERR, MessageKey.DATA: "Message"}),
        json.dumps({MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_DONE}),
    ]
    side_effects = messages + [websockets.exceptions.ConnectionClosed(None, None)]
    
    q = asyncio.Queue()
    for item in side_effects:
        await q.put(item)

    async def recv_side_effect():
        item = await q.get()
        if isinstance(item, Exception):
            raise item
        return item
    mock_ws.recv.side_effect = recv_side_effect
    
    # Act
    process = SandboxProcess(mock_ws)
    await process.exec("echo 'Hello World'", "bash")
    
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
    messages = [
        json.dumps({MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING}),
        json.dumps({MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "Chunk 1"}),
        json.dumps({MessageKey.EVENT: EventType.STDERR, MessageKey.DATA: "Error 1"}),
        json.dumps({MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "Chunk 2"}),
        json.dumps({MessageKey.EVENT: EventType.STDERR, MessageKey.DATA: "Error 2"}),
        json.dumps({MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_DONE}),
    ]
    side_effects = messages + [websockets.exceptions.ConnectionClosed(None, None)]
    
    q = asyncio.Queue()
    for item in side_effects:
        await q.put(item)

    async def recv_side_effect():
        item = await q.get()
        if isinstance(item, Exception):
            raise item
        return item
    mock_ws.recv.side_effect = recv_side_effect
    
    # Act
    process = SandboxProcess(mock_ws)
    await process.exec("some command", "bash")
    
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
async def test_process_exec_failure():
    """
    Tests that exec raises an exception if the server reports an error.
    """
    # Arrange
    mock_ws = AsyncMock()
    messages = [
        json.dumps({
            MessageKey.EVENT: EventType.STATUS_UPDATE,
            MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_ERROR,
            MessageKey.MESSAGE: "Something went wrong"
        }),
    ]
    side_effects = messages + [websockets.exceptions.ConnectionClosed(None, None)]
    
    q = asyncio.Queue()
    for item in side_effects:
        await q.put(item)

    async def recv_side_effect():
        item = await q.get()
        if isinstance(item, Exception):
            raise item
        return item
    mock_ws.recv.side_effect = recv_side_effect
    
    # Act & Assert
    process = SandboxProcess(mock_ws)
    with pytest.raises(SandboxExecutionError, match="Something went wrong"):
        await process.exec("some code", "python")

@pytest.mark.asyncio
async def test_process_terminate():
    """
    Tests that terminating a process correctly cancels the listener and cleans up.
    """
    # Arrange
    mock_ws = AsyncMock()
    
    messages = [
        json.dumps({MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING}),
        json.dumps({MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "Partial output"}),
    ]
    # After sending the initial messages, recv will block indefinitely.
    blocker = asyncio.Future()
    side_effects = messages + [blocker]

    q = asyncio.Queue()
    for item in side_effects:
        await q.put(item)

    async def recv_side_effect():
        item = await q.get()
        # The Future will block here until cancelled by terminate()
        if isinstance(item, asyncio.Future):
            await item
        return item
    mock_ws.recv.side_effect = recv_side_effect

    # Act
    process = SandboxProcess(mock_ws)
    await process.exec("some long-running command", "bash")
    
    # Confirm we received the first chunk of output
    first_chunk = await asyncio.wait_for(process.stdout.__aiter__().__anext__(), timeout=0.1)
    assert first_chunk == "Partial output"

    # Terminate the process while it's "running"
    await process.terminate()
    
    # Assert
    # The wait() should resolve immediately because terminate cleans up the listener
    await asyncio.wait_for(process.wait(), timeout=0.1)
    
    # The streams should be closed and contain the partial output
    stdout = await process.stdout.read_all()
    assert stdout == "" # The rest of the stream is empty

@pytest.mark.asyncio
async def test_process_terminate_while_reading():
    """
    Tests that a reader iterating a stream is unblocked gracefully when
    the process is terminated.
    """
    # Arrange
    mock_ws = AsyncMock()
    
    messages = [
        json.dumps({MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING}),
        json.dumps({MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "First chunk"}),
    ]
    # After the first chunk, recv will block indefinitely.
    blocker = asyncio.Future()
    side_effects = messages + [blocker]

    q = asyncio.Queue()
    for item in side_effects:
        await q.put(item)

    async def recv_side_effect():
        item = await q.get()
        if isinstance(item, asyncio.Future):
            await item
        return item
    mock_ws.recv.side_effect = recv_side_effect

    process = SandboxProcess(mock_ws)
    await process.exec("some long-running command", "bash")

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
    
    messages = [
        json.dumps({MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING}),
        json.dumps({MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "First chunk"}),
    ]
    # After the first chunk, recv will block indefinitely.
    blocker = asyncio.Future()
    side_effects = messages + [blocker]

    q = asyncio.Queue()
    for item in side_effects:
        await q.put(item)

    async def recv_side_effect():
        item = await q.get()
        if isinstance(item, asyncio.Future):
            await item
        return item
    mock_ws.recv.side_effect = recv_side_effect

    process = SandboxProcess(mock_ws)
    await process.exec("some long-running command", "bash")

    # Act
    # Start the .read_all() in the background
    reader_task = asyncio.create_task(process.stdout.read_all())

    # Give the reader a moment to start and consume the first chunk
    await asyncio.sleep(0)
    
    # Terminate the process while the reader is blocked
    await process.terminate()
    
    # Assert
    # The reader task should complete and return the partial content
    result = await asyncio.wait_for(reader_task, timeout=0.1)
    assert result == "First chunk"
    
    # The process should also report as done
    await asyncio.wait_for(process.wait(), timeout=0.1)

@pytest.mark.asyncio
async def test_process_connection_closed_before_start():
    """
    Tests that a connection closure before the process starts results in an error.
    """
    # Arrange
    mock_ws = AsyncMock()
    
    # The connection closes before the SANDBOX_EXECUTION_RUNNING message is received
    side_effects = [websockets.exceptions.ConnectionClosed(None, None)]
    
    q = asyncio.Queue()
    for item in side_effects:
        await q.put(item)

    async def recv_side_effect():
        item = await q.get()
        if isinstance(item, Exception):
            raise item
        return item
    mock_ws.recv.side_effect = recv_side_effect
    
    # Act & Assert
    process = SandboxProcess(mock_ws)
    with pytest.raises(SandboxConnectionError, match="Connection closed before execution started"):
        await process.exec("some code", "python")

@pytest.mark.asyncio
async def test_process_connection_closed_after_start():
    """
    Tests that a connection closure after the process has started is handled gracefully.
    """
    # Arrange
    mock_ws = AsyncMock()
    messages = [
        json.dumps({MessageKey.EVENT: EventType.STATUS_UPDATE, MessageKey.STATUS: SandboxEvent.SANDBOX_EXECUTION_RUNNING}),
        json.dumps({MessageKey.EVENT: EventType.STDOUT, MessageKey.DATA: "Partial output"}),
    ]
    # The connection dies mid-execution
    side_effects = messages + [websockets.exceptions.ConnectionClosed(None, None)]
    
    q = asyncio.Queue()
    for item in side_effects:
        await q.put(item)

    async def recv_side_effect():
        item = await q.get()
        if isinstance(item, Exception):
            raise item
        return item
    mock_ws.recv.side_effect = recv_side_effect
    
    # Act
    process = SandboxProcess(mock_ws)
    await process.exec("some command", "bash")
    
    # Wait for the process to finish (which it will, due to the connection error)
    await process.wait()
    
    # Assert
    # The process should not hang, and the partial output should be available.
    stdout = await process.stdout.read_all()
    assert stdout == "Partial output"
