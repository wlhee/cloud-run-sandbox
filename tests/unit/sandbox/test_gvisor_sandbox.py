import pytest
import asyncio
import shutil
import os
from src.sandbox.gvisor import GVisorConfig
from src.sandbox.factory import create_sandbox_config, create_sandbox_instance
from src.sandbox.types import OutputType, CodeLanguage, SandboxStateEvent
from src.sandbox.interface import SandboxCreationError,SandboxStreamClosed, SandboxError, SandboxOperationError

# Check if 'runsc' is in the PATH
runsc_path = shutil.which("runsc")

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_sandbox_create_and_delete():
    """
    Tests that the create() method correctly creates the bundle and root directories,
    and that the delete() method cleans them up.
    """
    sandbox_id = "gvisor-test-cleanup"
    
    # Use the factory to create the sandbox instance.
    sandbox = create_sandbox_instance(sandbox_id)
    
    root_dir = sandbox._root_dir
    bundle_dir = sandbox._bundle_dir
    
    # 1. Assert that directories do not exist yet.
    assert not os.path.exists(root_dir)
    assert not os.path.exists(bundle_dir)

    try:
        # 2. Create the sandbox.
        await sandbox.create()
        assert os.path.isdir(root_dir)
        assert os.path.isdir(bundle_dir)

    finally:
        # 3. Delete the sandbox and assert that directories are removed.
        await sandbox.delete()
        assert not os.path.exists(root_dir)
        assert not os.path.exists(bundle_dir)

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_sandbox_execute_python_success():
    """
    Tests that the execute() and connect() methods work correctly for a successful Python run.
    """
    sandbox_id = "gvisor-test-exec"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create() 
        
        code = "import sys; print('hello'); print('world', file=sys.stderr)"
        await sandbox.execute(CodeLanguage.PYTHON, code)

        events = []
        try:
            async for event in sandbox.connect():
                events.append(event)
        except SandboxStreamClosed:
            pass

        assert len(events) == 4
        assert events[0]["type"] == "status_update"
        assert events[0]["status"] == "SANDBOX_EXECUTION_RUNNING"
        assert events[1]["type"] == OutputType.STDOUT
        assert events[1]["data"].strip() == "hello"
        assert events[2]["type"] == OutputType.STDERR
        assert events[2]["data"].strip() == "world"
        assert events[3]["type"] == "status_update"
        assert events[3]["status"] == "SANDBOX_EXECUTION_DONE"

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_sandbox_execute_bash_success():
    """
    Tests that the execute() and connect() methods work correctly for bash code.
    """
    sandbox_id = "gvisor-test-bash"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create()
        
        code = "echo 'hello from bash' >&1; echo 'error from bash' >&2"
        await sandbox.execute(CodeLanguage.BASH, code)

        events = []
        try:
            async for event in sandbox.connect():
                events.append(event)
        except SandboxStreamClosed:
            pass

        assert len(events) == 4
        assert events[0]["type"] == "status_update"
        assert events[0]["status"] == "SANDBOX_EXECUTION_RUNNING"
        assert events[1]["type"] == OutputType.STDOUT
        assert events[1]["data"].strip() == "hello from bash"
        assert events[2]["type"] == OutputType.STDERR
        assert events[2]["data"].strip() == "error from bash"
        assert events[3]["type"] == "status_update"
        assert events[3]["status"] == "SANDBOX_EXECUTION_DONE"

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_sandbox_execute_python_syntax_error():
    """
    Tests that stderr is captured correctly when the executed Python code has a syntax error.
    """
    sandbox_id = "gvisor-test-syntax-error"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create()
        
        code = "import sys; print('hello'; print('world', file=sys.stderr)"
        await sandbox.execute(CodeLanguage.PYTHON, code)

        events = []
        try:
            async for event in sandbox.connect():
                events.append(event)
        except SandboxStreamClosed:
            pass

        assert len(events) > 2
        stderr = "".join([e["data"] for e in events if e.get("type") == OutputType.STDERR])
        assert "SyntaxError" in stderr

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_sandbox_execute_bash_error():
    """
    Tests that stderr is captured correctly when the executed bash script fails.
    """
    sandbox_id = "gvisor-test-bash-error"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create()
        
        code = "echo 'hello from bash' >&1; not_a_command"
        await sandbox.execute(CodeLanguage.BASH, code)

        events = []
        try:
            async for event in sandbox.connect():
                events.append(event)
        except SandboxStreamClosed:
            pass

        assert len(events) > 2
        stderr = "".join([e["data"] for e in events if e.get("type") == OutputType.STDERR])
        assert "command not found" in stderr

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_connect_before_execute_raises_error():
    """
    Tests that calling connect() before execute() raises a SandboxError.
    """
    sandbox_id = "gvisor-test-connect-fail"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create()
        with pytest.raises(SandboxError, match="No process is running"):
            async for _ in sandbox.connect():
                pass
    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_stop_during_execution():
    """
    Tests that stopping the sandbox during execution correctly terminates the stream.
    """
    sandbox_id = "gvisor-test-stop"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create()
        
        code = "import time; print('start'); time.sleep(5); print('end')"
        await sandbox.execute(CodeLanguage.PYTHON, code)

        events = []
        try:
            async for event in sandbox.connect():
                events.append(event)
                if event.get("type") == OutputType.STDOUT and "start" in event["data"]:
                    await sandbox.stop()
        except SandboxStreamClosed:
            pass

        assert len(events) == 3
        assert events[0]["type"] == "status_update"
        assert events[0]["status"] == "SANDBOX_EXECUTION_RUNNING"
        assert events[1]["type"] == OutputType.STDOUT
        assert events[1]["data"].strip() == "start"
        assert events[2]["type"] == "status_update"
        assert events[2]["status"] == "SANDBOX_EXECUTION_DONE"

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_stream_closes_after_execution():
    """
    Tests that the output stream closes automatically after the script finishes.
    This is a regression test for a bug where the stream would hang open.
    """
    sandbox_id = "gvisor-test-stream-close"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create() 
        
        code = "print('hello')"
        await sandbox.execute(CodeLanguage.PYTHON, code)

        all_events = []
        
        async def consume_stream():
            try:
                async for event in sandbox.connect():
                    all_events.append(event)
            except SandboxStreamClosed:
                pass

        # This test works by wrapping the stream consumption in a timeout.
        # If the stream hangs (the bug), `asyncio.wait_for` will raise a
        # `TimeoutError`, which is an unhandled exception that will cause
        # the test to fail.
        # If the stream closes correctly (the fix), the `consume_stream`
        # coroutine will complete successfully.
        await asyncio.wait_for(consume_stream(), timeout=5)

        assert len(all_events) == 3
        assert all_events[0]["status"] == "SANDBOX_EXECUTION_RUNNING"
        assert all_events[1]["data"].strip() == "hello"
        assert all_events[2]["status"] == "SANDBOX_EXECUTION_DONE"

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_sandbox_internet_access():
    """
    Tests that the sandbox can access the internet.
    """
    sandbox_id = "gvisor-test-internet"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create()
        
        code = "curl -s https://example.com"
        await sandbox.execute(CodeLanguage.BASH, code)

        events = []
        try:
            async for event in sandbox.connect():
                events.append(event)
        except SandboxStreamClosed:
            pass

        stdout = "".join([e["data"] for e in events if e.get("type") == OutputType.STDOUT])
        assert "Example Domain" in stdout

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_sandbox_writable_filesystem():
    """
    Tests that the sandbox has a writable filesystem.
    """
    sandbox_id = "gvisor-test-writable"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create()
        
        code = """
        mkdir -p /test_dir
        echo "hello world" > /test_dir/test_file.txt
        cat /test_dir/test_file.txt
        """
        await sandbox.execute(CodeLanguage.BASH, code)

        events = []
        try:
            async for event in sandbox.connect():
                events.append(event)
        except SandboxStreamClosed:
            pass

        stdout = "".join([e["data"] for e in events if e.get("type") == OutputType.STDOUT])
        assert "hello world" in stdout

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_multiple_executions():
    """
    Tests that multiple calls to execute() are handled correctly.
    """
    sandbox_id = "gvisor-test-multiple-exec"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create()
        
        # First execution
        await sandbox.execute(CodeLanguage.PYTHON, "print('first')")
        events = []
        try:
            async for event in sandbox.connect():
                events.append(event)
        except SandboxStreamClosed:
            pass
        
        assert len(events) == 3
        assert events[1]["data"].strip() == "first"

        # Second execution
        await sandbox.execute(CodeLanguage.BASH, "echo 'second'")
        events = []
        try:
            async for event in sandbox.connect():
                events.append(event)
        except SandboxStreamClosed:
            pass

        assert len(events) == 3
        assert events[1]["data"].strip() == "second"

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_reject_simultaneous_execution():
    """
    Tests that the sandbox rejects a new execution if one is already running.
    """
    sandbox_id = "gvisor-test-simultaneous"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create()
        
        # Start a long-running process
        long_running_code = "import time; print('start'); time.sleep(5); print('end')"
        await sandbox.execute(CodeLanguage.PYTHON, long_running_code)

        # Try to start another execution while the first is running
        with pytest.raises(SandboxOperationError, match="An execution is already in progress"):
            await sandbox.execute(CodeLanguage.PYTHON, "print('should fail')")

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_is_attached():
    """
    Tests the is_attached property of the GVisorSandbox.
    """
    sandbox_id = "gvisor-test-is-attached"
    sandbox = create_sandbox_instance(sandbox_id)
    try:
        await sandbox.create()
        assert not sandbox.is_attached
        sandbox.is_attached = True
        assert sandbox.is_attached
    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_sandbox_write_to_stdin():
    """
    Tests that the write_to_stdin method correctly writes to the process's stdin.
    """
    sandbox_id = "gvisor-test-stdin"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create()

        code = "line = input(); print(f'read: {line}')"
        await sandbox.execute(CodeLanguage.PYTHON, code)

        # This needs to be in a separate task because connect() will block
        # until the process is done, but the process won't be done until it
        # receives stdin.
        async def write_and_connect():
            await asyncio.sleep(0.1) # Give the process time to start
            await sandbox.write_to_stdin("hello\n")

            events = []
            try:
                async for event in sandbox.connect():
                    events.append(event)
            except SandboxStreamClosed:
                pass
            return events

        events = await asyncio.wait_for(write_and_connect(), timeout=5)

        stdout = "".join([e["data"] for e in events if e.get("type") == OutputType.STDOUT])
        assert "read: hello" in stdout

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_checkpoint_and_restore_fails_with_same_id():
    """
    Tests that restoring a checkpoint to the SAME container ID fails.
    This validates that 'runsc restore' is a creation operation.
    """
    sandbox_id = "gvisor-test-checkpoint-fail"
    checkpoint_dir = f"/tmp/checkpoint_{sandbox_id}"
    
    config = create_sandbox_config()
    config.network = "none"
    sandbox1 = create_sandbox_instance(sandbox_id, config=config)
    try:
        await sandbox1.create()
        await sandbox1.execute(CodeLanguage.BASH, "echo 'hello' > /test.txt")
        try:
            async for _ in sandbox1.connect(): pass
        except SandboxStreamClosed: pass
        
        os.makedirs(checkpoint_dir, exist_ok=True)
        await sandbox1.checkpoint(checkpoint_dir)
    finally:
        await sandbox1.delete()

    # Verify the container is gone from runsc's list
    list_cmd = sandbox1._build_runsc_cmd("list")
    stdout, _ = await sandbox1._run_sync_command(list_cmd)
    print("run list output:", stdout)
    assert sandbox_id not in stdout

    # Attempt to restore using the same ID, which is expected to fail.
    sandbox2 = create_sandbox_instance(sandbox_id, config=config)
    with pytest.raises(SandboxCreationError):
        await sandbox2.restore(checkpoint_dir)
    
    # Cleanup
    await sandbox2.delete()
    if os.path.exists(checkpoint_dir):
        shutil.rmtree(checkpoint_dir)


@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_checkpoint_and_restore_with_new_id():
    """
    Tests the full checkpoint and restore lifecycle using a NEW container ID,
    which is the correct workflow.
    """
    sandbox_id1 = "gvisor-test-checkpoint-1"
    sandbox_id2 = "gvisor-test-checkpoint-2"
    checkpoint_dir = f"/tmp/checkpoint_{sandbox_id1}"
    
    config = create_sandbox_config()
    config.network = "none"

    # 1. Create a sandbox and change its state
    sandbox1 = create_sandbox_instance(sandbox_id1, config=config)
    try:
        await sandbox1.create()
        await sandbox1.execute(CodeLanguage.BASH, "echo 'hello' > /test.txt")
        try:
            async for _ in sandbox1.connect(): pass
        except SandboxStreamClosed: pass
        
        os.makedirs(checkpoint_dir, exist_ok=True)
        await sandbox1.checkpoint(checkpoint_dir)
    finally:
        await sandbox1.delete()

    # 2. Create a new sandbox instance and restore it.
    # CRITICAL: The bundle and root paths must be the same as the original sandbox.
    sandbox2 = create_sandbox_instance(sandbox_id2, config=config)
    sandbox2._bundle_dir = sandbox1._bundle_dir 
    sandbox2._root_dir = sandbox1._root_dir

    try:
        await sandbox2.restore(checkpoint_dir)
        
        # 3. Verify the state was restored
        await sandbox2.execute(CodeLanguage.BASH, "cat /test.txt")
        events = []
        try:
            async for event in sandbox2.connect():
                events.append(event)
        except SandboxStreamClosed: pass
            
        stdout = "".join([e["data"] for e in events if e.get("type") == OutputType.STDOUT])
        assert "hello" in stdout
    finally:
        await sandbox2.delete()
        if os.path.exists(checkpoint_dir):
            shutil.rmtree(checkpoint_dir)

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_checkpoint_fails_if_running():
    """
    Tests that checkpointing fails if the sandbox is in the middle of an execution.
    """
    sandbox_id = "gvisor-test-checkpoint-fail"
    sandbox = create_sandbox_instance(sandbox_id)
    try:
        await sandbox.create()
        
        # Start a long-running process
        long_running_code = "import time; print('start'); time.sleep(5); print('end')"
        await sandbox.execute(CodeLanguage.PYTHON, long_running_code)

        # Try to checkpoint while the first is running
        with pytest.raises(SandboxOperationError, match="Cannot checkpoint while an execution is in progress"):
            await sandbox.checkpoint("/tmp/dummy_path")

    finally:
        await sandbox.delete()

