import pytest
import asyncio
from src.sandbox.process import Process

@pytest.mark.asyncio
async def test_process_lifecycle_and_streaming():
    """
    Tests the basic lifecycle: start, stream output from both streams, and wait.
    """
    cmd = ["bash", "-c", "echo 'hello'; echo 'world' >&2"]
    process = Process(cmd)

    assert not process.is_running
    await process.start()
    assert process.is_running

    # Concurrently stream stdout and stderr
    stdout_chunks = []
    stderr_chunks = []
    
    async def consume_stdout():
        async for data in process.stream_stdout():
            stdout_chunks.append(data)

    async def consume_stderr():
        async for data in process.stream_stderr():
            stderr_chunks.append(data)

    await asyncio.gather(consume_stdout(), consume_stderr())

    exit_code = await process.wait()
    assert not process.is_running
    assert exit_code == 0

    assert "".join(stdout_chunks).strip() == "hello"
    assert "".join(stderr_chunks).strip() == "world"

@pytest.mark.asyncio
async def test_process_stop():
    """
    Tests that the stop() method correctly terminates the process.
    """
    cmd = ["bash", "-c", "echo 'start'; sleep 5; echo 'end'"]
    process = Process(cmd)
    await process.start()
    assert process.is_running

    await process.stop()
    assert not process.is_running

@pytest.mark.asyncio
async def test_process_write_to_stdin():
    """
    Tests that write_to_stdin correctly sends data to the process.
    """
    cmd = ["python3", "-c", "import sys; line = sys.stdin.readline(); print(f'read: {line.strip()}')"]
    process = Process(cmd)
    await process.start()

    await process.write_to_stdin("hello\n")

    stdout_chunks = []
    async for data in process.stream_stdout():
        stdout_chunks.append(data)

    stdout = "".join(stdout_chunks)
    assert "read: hello" in stdout

    await process.wait()

@pytest.mark.asyncio
async def test_deadlock_prevention():
    """
    Tests that the process doesn't hang if only one stream is consumed
    while the other produces a large amount of output.
    """
    # This command writes 10KB to stderr, then a single line to stdout.
    # If stderr is not drained, this will hang.
    script = "import sys; sys.stderr.write('e' * 10000); sys.stderr.flush(); print('hello')"
    cmd = ["python3", "-c", script]
    process = Process(cmd)
    await process.start()

    # Only consume stdout
    stdout_chunks = []
    async for data in process.stream_stdout():
        stdout_chunks.append(data)

    stdout = "".join(stdout_chunks)
    assert "hello" in stdout

    await process.wait()
    await process.stop() # Clean up just in case

@pytest.mark.asyncio
async def test_runtime_errors():
    """
    Tests that methods raise RuntimeError if called out of order.
    """
    process = Process(["echo", "hello"])

    with pytest.raises(RuntimeError, match="Process has not been started yet."):
        async for _ in process.stream_stdout():
            pass

    with pytest.raises(RuntimeError, match="Process has not been started yet."):
        await process.wait()

    await process.start()
    with pytest.raises(RuntimeError, match="Process has already been started."):
        await process.start()
    
    await process.stop()

@pytest.mark.asyncio
async def test_stop_unblocks_stream_readers():
    """
    Tests that stop() unblocks consumers waiting on stream_stdout or stream_stderr.
    """
    # This process prints to both streams and then sleeps forever.
    cmd = ["bash", "-c", "echo 'out'; echo 'err' >&2; sleep 30"]
    process = Process(cmd)
    await process.start()
    assert process.is_running

    stdout_read_event = asyncio.Event()
    stderr_read_event = asyncio.Event()

    async def consume_stdout():
        async for _ in process.stream_stdout():
            stdout_read_event.set() # Signal that we've read the first chunk
        # The loop should terminate cleanly when stop() is called.

    async def consume_stderr():
        async for _ in process.stream_stderr():
            stderr_read_event.set() # Signal that we've read the first chunk
        # The loop should terminate cleanly when stop() is called.

    # Start the consumers and wait for them to read the initial output and block.
    consumer_tasks = [
        asyncio.create_task(consume_stdout()),
        asyncio.create_task(consume_stderr()),
    ]
    await asyncio.wait_for(stdout_read_event.wait(), timeout=1)
    await asyncio.wait_for(stderr_read_event.wait(), timeout=1)

    # Now that the consumers are blocked waiting for more data, stop the process.
    await process.stop()

    # The consumer tasks should now unblock and finish.
    # We await them with a timeout to prove they don't hang.
    await asyncio.wait_for(asyncio.gather(*consumer_tasks), timeout=1)

    exit_code = await process.wait()
    assert exit_code != 0


