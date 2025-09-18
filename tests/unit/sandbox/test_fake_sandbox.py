import pytest
import asyncio
import os
import tempfile
from unittest.mock import AsyncMock
from src.sandbox.fake import FakeSandbox, FakeSandboxConfig, ExecConfig
from src.sandbox.interface import SandboxCreationError, SandboxOperationError, SandboxStreamClosed
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
    
    await sandbox.delete()

async def test_fake_sandbox_create_error():
    """
    Tests that the FakeSandbox correctly raises a SandboxCreationError.
    """
    config = FakeSandboxConfig(create_should_fail=True)
    sandbox = FakeSandbox("fake-error", config=config)
    
    with pytest.raises(SandboxCreationError):
        await sandbox.create()

async def test_fake_sandbox_is_attached():
    """
    Tests the is_attached property of the FakeSandbox.
    """
    sandbox = FakeSandbox("fake-123")
    assert not sandbox.is_attached
    sandbox.is_attached = True
    assert sandbox.is_attached

async def test_fake_sandbox_delete():
    """
    Tests that the delete method works.
    """
    sandbox = FakeSandbox("fake-123")
    await sandbox.create()
    await sandbox.delete()

async def test_fake_sandbox_write_to_stdin():
    """
    Tests that the write_to_stdin method correctly validates the input.
    """
    config = FakeSandboxConfig(executions=[ExecConfig(expected_stdin=["hello\n"])])
    sandbox = FakeSandbox("fake-123", config=config)

    await sandbox.create()
    await sandbox.execute(CodeLanguage.PYTHON, "some code")

    await sandbox.write_to_stdin("hello\n")

    with pytest.raises(AssertionError):
        await sandbox.write_to_stdin("world\n")

async def test_fake_sandbox_checkpoint_and_restore():
    """
    Tests that the FakeSandbox can be checkpointed and restored successfully.
    """
    sandbox = FakeSandbox("fake-checkpoint")
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        checkpoint_path = tmp.name

    # Checkpoint should create the file
    await sandbox.create()
    await sandbox.checkpoint(checkpoint_path)
    assert os.path.exists(checkpoint_path)

    # Restore should succeed
    sandbox2 = FakeSandbox("fake-restore")
    await sandbox2.restore(checkpoint_path)
    
    os.remove(checkpoint_path)

async def test_fake_sandbox_checkpoint_fails_if_running():
    """
    Tests that checkpointing fails if the sandbox is in the middle of an execution.
    """
    config = FakeSandboxConfig(executions=[ExecConfig()])
    sandbox = FakeSandbox("fake-checkpoint-fail", config=config)
    await sandbox.create()
    await sandbox.execute(CodeLanguage.PYTHON, "code")

    with pytest.raises(SandboxOperationError, match="Cannot checkpoint while an execution is in progress."):
        await sandbox.checkpoint("/tmp/dummy_path")

async def test_fake_sandbox_restore_fails_if_no_checkpoint():
    """
    Tests that restoring fails if the checkpoint file does not exist.
    """
    sandbox = FakeSandbox("fake-restore-fail")
    non_existent_path = "/tmp/non_existent_checkpoint"
    assert not os.path.exists(non_existent_path)

    with pytest.raises(SandboxOperationError, match=f"Checkpoint file not found at {non_existent_path}"):
        await sandbox.restore(non_existent_path)
