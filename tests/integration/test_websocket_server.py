import pytest
from fastapi.testclient import TestClient
from src.server import app

client = TestClient(app)

def test_websocket_attach_not_found():
    """
    Tests attaching to a non-existent sandbox via WebSocket.
    """
    with client.websocket_connect("/attach/non-existent-sandbox") as websocket:
        data = websocket.receive_json()
        assert data == {"event": "status_update", "status": "SANDBOX_NOT_FOUND"}