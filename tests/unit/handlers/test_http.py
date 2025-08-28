import pytest
from fastapi.testclient import TestClient
from src.server import app
from unittest.mock import patch, AsyncMock
from src.sandbox.fake import FakeSandbox, FakeSandboxConfig, ExecConfig
from src.sandbox.types import SandboxOutputEvent, OutputType, CodeLanguage
from src.sandbox.interface import SandboxStreamClosed
from src.handlers.http import execute_code_streaming
from fastapi import BackgroundTasks

client = TestClient(app)

@patch('src.handlers.http.list_containers')
def test_list_containers_success(mock_list_containers):
    """Tests the successful listing of containers."""
    mock_list_containers.return_value = ("container1\ncontainer2", None)
    
    response = client.get("/list")
    assert response.status_code == 200
    assert response.json() == {"containers": "container1\ncontainer2"}

@patch('src.handlers.http.sandbox_manager')
def test_execute_code_streaming(mock_manager):
    """Tests the streaming execution of code."""
    # Arrange
    output_stream = [
        SandboxOutputEvent(type=OutputType.STDOUT, data="line 1\n"),
        SandboxOutputEvent(type=OutputType.STDOUT, data="line 2\n"),
    ]
    config = FakeSandboxConfig(executions=[ExecConfig(output_stream=output_stream)])
    sandbox = FakeSandbox("fake-sandbox-http", config=config)
    sandbox.execute = AsyncMock() # Mock the execute method
    
    mock_manager.create_sandbox = AsyncMock(return_value=sandbox)
    mock_manager.delete_sandbox = AsyncMock()

    # Act
    response = client.post(
        "/execute?language=python",
        content="print('hello')",
        headers={"Content-Type": "text/plain"}
    )

    # Assert
    assert response.status_code == 200
    assert response.text == "line 1\nline 2\n"
    mock_manager.create_sandbox.assert_called_once()
    sandbox.execute.assert_called_once_with(CodeLanguage.PYTHON, "print('hello')")
    mock_manager.delete_sandbox.assert_called_once_with("fake-sandbox-http")

@pytest.mark.asyncio
@patch('src.handlers.http.sandbox_manager')
async def test_execute_code_streaming_handles_stream_closed(mock_manager):
    """
    Tests that the execute_code_streaming generator handles SandboxStreamClosed gracefully.
    """
    # Arrange
    sandbox = FakeSandbox("fake-sandbox-stream-closed")
    sandbox.execute = AsyncMock()
    
    async def mock_connect():
        yield SandboxOutputEvent(type=OutputType.STDOUT, data="line 1\n")
        raise SandboxStreamClosed()

    sandbox.connect = mock_connect
    
    mock_manager.create_sandbox = AsyncMock(return_value=sandbox)
    mock_manager.delete_sandbox = AsyncMock()
    
    background_tasks = BackgroundTasks()

    # Act
    stream = [item async for item in execute_code_streaming(CodeLanguage.PYTHON, "test", background_tasks)]
    
    # Manually run the background tasks
    for task in background_tasks.tasks:
        await task()

    # Assert
    assert len(stream) == 1
    assert stream[0] == b"line 1\n"
    mock_manager.delete_sandbox.assert_called_once_with("fake-sandbox-stream-closed")