import pytest
import asyncio
import shutil
from src.sandbox.gvisor import GVisorSandbox
from src.sandbox.events import OutputType

# Check if 'runsc' is in the PATH
runsc_path = shutil.which("runsc")

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_hello_world():
    """
    Tests a full, end-to-end lifecycle of the GVisorSandbox by running
    a simple 'hello world' script.
    """
    sandbox = GVisorSandbox("gvisor-test-123")
    
    try:
        # 1. Create and start the sandbox
        await sandbox.create()
        await sandbox.start(code="print('hello from gvisor')")

        # 2. Connect and get the output
        output = []
        async for event in sandbox.connect():
            output.append(event)
            # We only expect one line of output, so we can break
            break
        
        # 3. Assert the output is correct
        assert len(output) == 1
        assert output[0]["type"] == OutputType.STDOUT
        assert output[0]["data"] == "hello from gvisor\n"

    finally:
        # 4. Clean up the sandbox
        await sandbox.delete()