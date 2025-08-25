import pytest
from fastapi.testclient import TestClient
from src.server import app
from unittest.mock import patch, AsyncMock
from src.sandbox.fake import FakeSandbox, FakeSandboxConfig
from src.sandbox.types import SandboxOutputEvent, OutputType, CodeLanguage

client = TestClient(app)

@patch('src.handlers.http.sandbox_manager')
def test_list_sandboxes(mock_manager):
    """Tests the successful listing of sandboxes."""
    mock_manager.list_sandboxes.return_value = ["sandbox1", "sandbox2"]
    
    response = client.get("/list")
    assert response.status_code == 200
    assert response.json() == {"sandboxes": ["sandbox1", "sandbox2"]}

@patch('src.handlers.http.sandbox_manager')
def test_execute_code_streaming(mock_manager):
    """Tests the streaming execution of code."""
    # Arrange
    output_stream = [
        SandboxOutputEvent(type=OutputType.STDOUT, data="line 1\n"),
        SandboxOutputEvent(type=OutputType.STDOUT, data="line 2\n"),
    ]
    config = FakeSandboxConfig(output_messages=output_stream)
    sandbox = FakeSandbox("fake-sandbox-http", config=config)
    
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
