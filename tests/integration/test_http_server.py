import pytest
from fastapi.testclient import TestClient
from src.server import app
from unittest.mock import patch

client = TestClient(app)

def test_status_endpoint():
    """Tests the GET /status endpoint."""
    response = client.get("/status")
    assert response.status_code == 200
    assert response.text == "Server is running"

@patch('src.handlers.http.execute_code_streaming')
def test_execute_streaming_mocked(mock_execute):
    """
    Tests the POST /execute endpoint with a mocked streaming function.
    """
    # Arrange: Configure the mock to return a simple async generator
    async def mock_stream_gen():
        yield b"line 1\n"
        yield b"line 2\n"
    
    mock_execute.return_value = mock_stream_gen()

    # Act
    response = client.post(
        "/execute",
        content="print('hello')",
        headers={"Content-Type": "text/plain"}
    )

    # Assert
    assert response.status_code == 200
    assert response.text == "line 1\nline 2\n"
    mock_execute.assert_called_once_with("print('hello')")