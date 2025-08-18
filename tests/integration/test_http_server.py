import pytest
from fastapi.testclient import TestClient
from src.server import app
from unittest.mock import patch, AsyncMock
import asyncio

client = TestClient(app)

def test_status_endpoint():
    """Tests the GET /status endpoint."""
    response = client.get("/status")
    assert response.status_code == 200
    assert "Server is running" in response.text

@pytest.mark.asyncio
@patch('src.sandbox.manager.execute_code_streaming')
async def test_execute_streaming_mocked(mock_execute_code):
    """
    Tests the POST /execute endpoint with a mocked gVisor subprocess.
    This test can be run locally without needing runsc.
    """
    
    async def mock_streamer(code):
        yield b"hello from sandbox\n"
        yield b"error from sandbox\n"

    mock_execute_code.return_value = mock_streamer("test code")

    code = "import sys; print('hello from sandbox'); sys.stderr.write('error from sandbox\n')"
    
    response = client.post(
        "/execute",
        content=code,
        headers={"Content-Type": "text/plain"}
    )

    assert response.status_code == 200
    assert "hello from sandbox" in response.text
    assert "error from sandbox" in response.text
    mock_execute_code.assert_called_once_with(code)

@pytest.mark.real
def test_execute_streaming_real():
    """
    Tests the POST /execute endpoint with a real, simple script.
    This is an end-to-end test that will actually run gVisor.
    It should be skipped when running locally on a non-Linux OS.
    """
    code = "import sys; print('hello from sandbox'); sys.stderr.write('error from sandbox\n')"
    
    response = client.post(
        "/execute",
        content=code,
        headers={"Content-Type": "text/plain"}
    )

    assert response.status_code == 200
    assert "hello from sandbox" in response.text
    assert "error from sandbox" in response.text