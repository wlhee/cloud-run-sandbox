import pytest
from fastapi.testclient import TestClient
from src.server import app
from unittest.mock import patch, AsyncMock

client = TestClient(app)

@patch('src.handlers.http.list_containers')
def test_list_containers_success(mock_list_containers):
    """Tests the successful listing of containers."""
    mock_list_containers.return_value = ("container1\ncontainer2", None)
    
    response = client.get("/containers")
    assert response.status_code == 200
    assert response.json() == {"containers": "container1\ncontainer2"}

@patch('src.handlers.http.list_containers')
def test_list_containers_error(mock_list_containers):
    """Tests an error during container listing."""
    mock_list_containers.return_value = (None, "gVisor error")
    
    response = client.get("/containers")
    assert response.status_code == 500
    assert response.json() == {"detail": "gVisor error"}

@patch('src.handlers.http.execute_code_streaming')
def test_execute_code_streaming(mock_execute):
    """Tests the streaming execution of code."""
    async def mock_stream():
        yield b"line 1\n"
        yield b"line 2\n"
    mock_execute.return_value = mock_stream()

    response = client.post(
        "/execute",
        content="print('hello')",
        headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 200
    assert response.text == "line 1\nline 2\n"