import pytest
from fastapi.testclient import TestClient
from src.server import app
from unittest.mock import patch, AsyncMock
import asyncio

client = TestClient(app)

@patch('src.sandbox.manager.list_containers', new_callable=AsyncMock)
def test_list_containers_success(mock_list_containers):
    """Tests a successful GET /list request."""
    mock_list_containers.return_value = ("container1\ncontainer2", None)
    
    response = client.get("/list")
    
    assert response.status_code == 200
    assert response.text == "container1\ncontainer2"
    mock_list_containers.assert_awaited_once()

@patch('src.sandbox.manager.list_containers', new_callable=AsyncMock)
def test_list_containers_error(mock_list_containers):
    """Tests a failed GET /list request."""
    mock_list_containers.return_value = (None, "An error occurred")
    
    response = client.get("/list")
    
    assert response.status_code == 500
    assert response.text == "An error occurred"

@patch('src.sandbox.manager.execute_code_streaming')
def test_execute_code_streaming(mock_execute_code):
    """Tests the POST /execute streaming endpoint."""
    
    async def mock_streamer(code):
        yield b"line 1\n"
        yield b"line 2\n"

    # We need to mock the return value of the async function
    mock_execute_code.return_value = mock_streamer("test code")

    response = client.post(
        "/execute", 
        content="test code", 
        headers={"Content-Type": "text/plain"}
    )

    assert response.status_code == 200
    assert response.text == "line 1\nline 2\n"
    mock_execute_code.assert_called_once_with("test code")
