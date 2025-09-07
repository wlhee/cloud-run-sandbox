import pytest
import asyncio
from src.sandbox.fake import FakeSandbox, FakeSandboxConfig, ExecConfig
from src.sandbox.interface import SandboxCreationError, SandboxStreamClosed
from src.sandbox.types import SandboxOutputEvent, OutputType, CodeLanguage, SandboxStateEvent

pytestmark = pytest.mark.asyncio

async def test_fake_sandbox_lifecycle_and_output():
    """
    Tests the full lifecycle and output streaming of the FakeSandbox.
    """
    # Configure the fake sandbox to produce a specific stream of events
    output_stream: list[SandboxOutputEvent] = [
        {"type": OutputType.STDOUT, "data": "line 1"},
        {"type": OutputType.STDERR, "data": "error 1"},
        {"type": OutputType.STDOUT, "data": "line 2"},
    ]
    config = FakeSandboxConfig(executions=[ExecConfig(output_stream=output_stream)])
    sandbox = FakeSandbox("fake-123", config=config)

    # 1. Create and start
    await sandbox.create()
    await sandbox.execute(CodeLanguage.PYTHON, "some code")
    assert sandbox.is_running

    # 2. Connect and verify the output stream
    messages = []
    try:
        async for msg in sandbox.connect():
            messages.append(msg)
    except SandboxStreamClosed:
        pass  # Expected at the end of the stream

    # Convert the received messages for comparison
    received_messages = [{"type": msg.get("type"), "data": msg.get("data"), "status": msg.get("status")} for msg in messages]
    expected_messages = [
        {"type": "status_update", "status": "SANDBOX_EXECUTION_RUNNING", "data": None},
        {"type": OutputType.STDOUT, "data": "line 1", "status": None},
        {"type": OutputType.STDERR, "data": "error 1", "status": None},
        {"type": OutputType.STDOUT, "data": "line 2", "status": None},
        {"type": "status_update", "status": "SANDBOX_EXECUTION_DONE", "data": None},
    ]

    assert received_messages == expected_messages
    
    # 3. The sandbox should not be running after the stream is closed
    assert not sandbox.is_running
    await sandbox.stop()
    assert not sandbox.is_running

async def test_fake_sandbox_create_error():
    """
    Tests that the FakeSandbox correctly raises a SandboxCreationError.
    """
    config = FakeSandboxConfig(create_should_fail=True)
    sandbox = FakeSandbox("fake-error", config=config)
    
    with pytest.raises(SandboxCreationError):
        await sandbox.create()