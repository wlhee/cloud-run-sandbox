import pytest
import asyncio
from src.sandbox.execution import Execution
from src.sandbox.types import OutputType
from src.sandbox.interface import SandboxStreamClosed

pytestmark = pytest.mark.asyncio

async def test_execution_streaming():
    """Tests that the Execution class correctly streams process output."""
    # Arrange
    process = await asyncio.create_subprocess_exec(
        "bash", "-c", "echo 'hello'; echo 'error' >&2",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    execution = Execution(process)
    await execution.start_streaming()

    # Act
    events = []
    try:
        async for event in execution.connect():
            events.append(event)
    except SandboxStreamClosed:
        pass

    # Assert
    assert len(events) == 2
    assert {"type": OutputType.STDOUT, "data": "hello\n"} in events
    assert {"type": OutputType.STDERR, "data": "error\n"} in events

async def test_execution_stop():
    """Tests that the stop method correctly terminates the process."""
    # Arrange
    process = await asyncio.create_subprocess_exec(
        "bash", "-c", "sleep 5",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    execution = Execution(process)
    await execution.start_streaming()

    # Act
    await execution.stop()

    # Assert
    assert process.returncode is not None

async def test_process_crashes_immediately():
    """
    Tests that the Execution class handles a process that crashes immediately.
    The stream should close without returning any data.
    """
    # Arrange
    process = await asyncio.create_subprocess_exec(
        "bash", "-c", "exit 1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    execution = Execution(process)
    await execution.start_streaming()

    # Act
    events = []
    try:
        async for event in execution.connect():
            events.append(event)
    except SandboxStreamClosed:
        pass

    # Assert
    assert len(events) == 0

async def test_process_killed_during_streaming():
    """
    Tests that the Execution class handles a process that is externally
    killed in the middle of streaming output. The partial output should be
    received before the stream closes.
    """
    # Arrange: Start a process that prints one line then waits indefinitely.
    process = await asyncio.create_subprocess_exec(
        "bash", "-c", "echo 'hello'; sleep 10",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    execution = Execution(process)
    await execution.start_streaming()

    # Act: Consume the first event, then kill the process to simulate a crash.
    events = []
    try:
        async for event in execution.connect():
            events.append(event)
            if "hello" in event["data"]:
                process.kill()
    except SandboxStreamClosed:
        pass

    # Assert
    assert len(events) == 1
    assert events[0]["type"] == OutputType.STDOUT
    assert events[0]["data"] == "hello\n"