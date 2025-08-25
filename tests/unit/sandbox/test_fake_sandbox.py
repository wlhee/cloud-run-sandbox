import pytest
import asyncio
from src.sandbox.fake import FakeSandbox, FakeSandboxConfig
from src.sandbox.interface import SandboxCreationError, SandboxStartError
from src.sandbox.events import SandboxOutputEvent, OutputType

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
    config = FakeSandboxConfig(output_messages=output_stream)
    sandbox = FakeSandbox("fake-123", config=config)

    # 1. Create and start
    await sandbox.create()
    await sandbox.execute("some code")
    assert sandbox.is_running

    # 2. Connect and verify the output stream
    messages = [msg async for msg in sandbox.connect()]
    
    # Convert the received messages for comparison
    received_messages = [{"type": msg["type"].value, "data": msg["data"]} for msg in messages]
    expected_messages = [{"type": "stdout", "data": "line 1"},
                         {"type": "stderr", "data": "error 1"},
                         {"type": "stdout", "data": "line 2"}]

    assert received_messages == expected_messages
    
    # 3. The sandbox should remain running until explicitly stopped
    assert sandbox.is_running
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

async def test_fake_sandbox_start_error():
    """
    Tests that the FakeSandbox correctly raises a SandboxStartError.
    """
    config = FakeSandboxConfig(start_should_fail=True)
    sandbox = FakeSandbox("fake-error", config=config)
    
    with pytest.raises(SandboxStartError):
        await sandbox.execute("any code")