import pytest
import asyncio
import shutil
from src.sandbox.factory import create_sandbox_instance
from src.sandbox.events import OutputType
from src.sandbox.interface import SandboxStreamClosed

# Check if 'runsc' is in the PATH
runsc_path = shutil.which("runsc")

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_hello_world():
    """
    Tests a full, end-to-end lifecycle of the GVisorSandbox by running
    a simple 'hello world' script and checking for its output.
    """
    print(f"Creating sandbox instance with ID 'gvisor-test-123'")

    sandbox = create_sandbox_instance("gvisor-test-123")

    print(f"Done sandbox instance with ID 'gvisor-test-123'")

    
    try:
        # 1. Create and start the sandbox
        print(f"calling sandbox.create())")

        await sandbox.create()

        print(f"calling sandbox.start())")

        await sandbox.start(code="import sys; print('hello from gvisor'); sys.stderr.write('an error message\n')")

        print(f"Sandbox started, now connecting to output stream.")
        # 2. Connect and collect all output
        output_events = []
        try:
            async for event in sandbox.connect():
                output_events.append(event)
        except SandboxStreamClosed:
            pass # This is the expected end of the stream
        
        # 3. Assert that the expected output is present
        stdout_messages = [e['data'] for e in output_events if e['type'].value == 'stdout']
        stderr_messages = [e['data'] for e in output_events if e['type'].value == 'stderr']

        assert "hello from gvisor\n" in stdout_messages
        assert "an error message\n" in stderr_messages

    finally:
        # 4. Clean up the sandbox
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_stream_closes():
    """
    Tests that the connect() stream correctly raises SandboxStreamClosed
    when the sandbox process finishes.
    """
    sandbox = create_sandbox_instance("gvisor-test-closes")
    
    try:
        await sandbox.create()
        await sandbox.start(code="print('short script')")

        # The context manager will assert that the exception is raised.
        with pytest.raises(SandboxStreamClosed):
            # This single loop will consume all events and then raise the exception.
            async for event in sandbox.connect():
                print(f"Received event: {event}") # for debugging

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_multiple_connections():
    """
    Tests that multiple clients can connect to the same sandbox and receive
    the output stream without interfering with each other.
    """
    sandbox = create_sandbox_instance("gvisor-test-multi")
    client1_connected = asyncio.Event()
    
    async def client1_listener():
        nonlocal client1_output
        try:
            async for event in sandbox.connect():
                client1_output.append(event)
                if "first" in event['data']:
                    client1_connected.set()
        except SandboxStreamClosed:
            pass

    async def client2_listener():
        nonlocal client2_output
        try:
            async for event in sandbox.connect():
                client2_output.append(event)
        except SandboxStreamClosed:
            pass

    try:
        await sandbox.create()
        await sandbox.start(code="import time; print('first'); time.sleep(0.1); print('second')")

        client1_output = []
        client2_output = []

        # Start client 1
        task1 = asyncio.create_task(client1_listener())
        
        # Wait for client 1 to connect and receive the first message
        await client1_connected.wait()

        # Start client 2
        task2 = asyncio.create_task(client2_listener())

        # Wait for both clients to finish
        await asyncio.gather(task1, task2)

        # Assertions
        client1_stdout = [e['data'] for e in client1_output if e['type'].value == 'stdout']
        client2_stdout = [e['data'] for e in client2_output if e['type'].value == 'stdout']

        assert "first\n" in client1_stdout
        assert "second\n" in client1_stdout
        
        assert "first\n" not in client2_stdout
        assert "second\n" in client2_stdout

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_disconnect_reconnect():
    """
    Tests that a client can disconnect and a new client can reconnect,
    receiving only the new output.
    """
    sandbox = create_sandbox_instance("gvisor-test-reconnect")
    first_message_received = asyncio.Event()

    async def client1_listener():
        # Client 1 connects, gets the first line, and disconnects.
        nonlocal client1_output
        async for event in sandbox.connect():
            client1_output.append(event)
            if "first" in event['data']:
                first_message_received.set()
                break # Disconnect

    async def client2_listener():
        # Client 2 connects and gets the rest of the output.
        nonlocal client2_output
        try:
            async for event in sandbox.connect():
                client2_output.append(event)
        except SandboxStreamClosed:
            pass # Expected end of stream

    try:
        await sandbox.create()
        await sandbox.start(code="import time; print('first'); time.sleep(0.1); print('second')")

        client1_output = []
        client2_output = []

        # Run client 1 and wait for it to disconnect
        await client1_listener()
        
        # Ensure client 1 has set the event before proceeding
        await first_message_received.wait()

        # Run client 2 to capture the rest of the output
        await client2_listener()

        # Assertions
        client1_stdout = [e['data'] for e in client1_output if e['type'].value == 'stdout']
        client2_stdout = [e['data'] for e in client2_output if e['type'].value == 'stdout']

        assert "first\n" in client1_stdout
        assert "second\n" not in client1_stdout

        assert "first\n" not in client2_stdout
        assert "second\n" in client2_stdout

    finally:
        await sandbox.delete()

@pytest.mark.asyncio
@pytest.mark.skipif(not runsc_path, reason="runsc command not found in PATH")
async def test_gvisor_sandbox_slow_consumer():
    """
    Tests that a slow consumer will still receive all messages even if the
    sandbox process finishes before the consumer is done reading.
    """
    sandbox = create_sandbox_instance("gvisor-test-slow")
    
    try:
        await sandbox.create()
        # This script will print 10 lines and then exit immediately.
        await sandbox.start(code="for i in range(10): print(f'line {i}')")

        output_events = []
        with pytest.raises(SandboxStreamClosed):
            async for event in sandbox.connect():
                output_events.append(event)
                # Simulate a slow consumer
                await asyncio.sleep(0.05)

        # Assert that we received all 10 lines, even though the producer
        # finished long before the consumer.
        assert len(output_events) == 10
        for i in range(10):
            assert f"line {i}\n" in [e['data'] for e in output_events]

    finally:
        await sandbox.delete()