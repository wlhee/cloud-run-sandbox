import pytest
import asyncio
import shutil
import os
from src.sandbox.factory import create_sandbox_instance
from src.sandbox.events import OutputType

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
async def test_sandbox_execute_and_connect():
    """
    Tests that the execute() and connect() methods work correctly.
    """
    sandbox_id = "gvisor-test-exec"
    sandbox = create_sandbox_instance(sandbox_id)

    try:
        await sandbox.create()
        
        code = "import sys; print('hello'); print('world', file=sys.stderr)"
        await sandbox.execute(code)

        # Collect all events from the stream
        events = [event async for event in sandbox.connect()]

        # Verify the output
        assert len(events) == 2
        assert events[0]["type"] == OutputType.STDOUT
        assert events[0]["data"].strip() == "hello"
        assert events[1]["type"] == OutputType.STDERR
        assert events[1]["data"].strip() == "world"

    finally:
        await sandbox.delete()
