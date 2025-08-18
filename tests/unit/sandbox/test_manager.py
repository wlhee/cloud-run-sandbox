import pytest
from unittest.mock import patch, AsyncMock
from src.sandbox import manager
import asyncio

pytestmark = pytest.mark.asyncio

@patch('asyncio.create_subprocess_exec')
async def test_list_containers_success(mock_exec):
    """Tests a successful call to list_containers."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"ID-1\nID-2\n", b"")
    mock_exec.return_value = mock_proc

    output, err = await manager.list_containers()

    mock_exec.assert_awaited_once_with(
        "runsc", "list",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    assert output == "ID-1\nID-2\n"
    assert err is None

@patch('asyncio.create_subprocess_exec')
async def test_list_containers_failure(mock_exec):
    """Tests a failed call to list_containers."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate.return_value = (b"", b"error")
    mock_exec.return_value = mock_proc

    output, err = await manager.list_containers()

    assert output is None
    assert "error" in err

@patch('asyncio.create_subprocess_exec')
async def test_suspend_container(mock_exec):
    """Tests a successful call to suspend_container."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")
    mock_exec.return_value = mock_proc
    
    container_id = "test-container"
    output, err = await manager.suspend_container(container_id)

    mock_exec.assert_awaited_once_with(
        "runsc", "pause", container_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    assert f"App {container_id} suspended" in output
    assert err is None

@patch('asyncio.create_subprocess_exec')
async def test_resume_container(mock_exec):
    """Tests a successful call to resume_container."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")
    mock_exec.return_value = mock_proc
    
    container_id = "test-container"
    output, err = await manager.resume_container(container_id)

    mock_exec.assert_awaited_once_with(
        "runsc", "resume", container_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    assert f"App {container_id} restored" in output
    assert err is None

@patch('asyncio.create_subprocess_exec')
async def test_delete_container(mock_exec):
    """Tests a successful call to delete_container."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")
    mock_exec.return_value = mock_proc
    
    container_id = "test-container"
    output, err = await manager.delete_container(container_id)

    mock_exec.assert_awaited_once_with(
        "runsc", "delete", container_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    assert f"App {container_id} deleted" in output
    assert err is None