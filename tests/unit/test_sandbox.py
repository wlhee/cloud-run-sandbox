import pytest
from unittest.mock import patch, MagicMock
from src import sandbox

@patch('subprocess.run')
def test_list_containers_success(mock_run):
    """
    Tests that list_containers correctly parses the output of 'runsc list'.
    """
    # Mock the return value of subprocess.run
    mock_result = MagicMock()
    mock_result.stdout = "ID-1\nID-2\n"
    mock_run.return_value = mock_result

    # Call the function
    output, err = sandbox.list_containers()

    # Assert that subprocess.run was called correctly
    mock_run.assert_called_once_with(
        ["runsc", "list"], check=True, capture_output=True, text=True
    )

    # Assert that the function returned the correct output
    assert output == "ID-1\nID-2\n"
    assert err is None

@patch('subprocess.run')
def test_list_containers_failure(mock_run):
    """
    Tests that list_containers correctly handles an error from 'runsc list'.
    """
    # Mock an exception being raised by subprocess.run
    mock_run.side_effect = Exception("runsc command failed")

    # Call the function
    output, err = sandbox.list_containers()

    # Assert that the function returned the correct error message
    assert output is None
    assert "runsc command failed" in err

@patch('subprocess.run')
def test_suspend_container(mock_run):
    """
    Tests that suspend_container calls the correct 'runsc pause' command.
    """
    container_id = "test-container"
    output, err = sandbox.suspend_container(container_id)
    
    mock_run.assert_called_once_with(["runsc", "pause", container_id], check=True)
    assert f"App {container_id} suspended" in output
    assert err is None

@patch('subprocess.run')
def test_resume_container(mock_run):
    """
    Tests that resume_container calls the correct 'runsc resume' command.
    """
    container_id = "test-container"
    output, err = sandbox.resume_container(container_id)
    
    mock_run.assert_called_once_with(["runsc", "resume", container_id], check=True)
    assert f"App {container_id} restored" in output
    assert err is None

@patch('subprocess.run')
def test_delete_container(mock_run):
    """
    Tests that delete_container calls the correct 'runsc delete' command.
    """
    container_id = "test-container"
    output, err = sandbox.delete_container(container_id)
    
    mock_run.assert_called_once_with(["runsc", "delete", container_id], check=True)
    assert f"App {container_id} deleted" in output
    assert err is None