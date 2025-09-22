import asyncio
import json
import os
import unittest
from unittest.mock import MagicMock, patch, AsyncMock, mock_open

import pytest
from src.sandbox.gvisor import GVisorConfig, GVisorSandbox

@pytest.fixture
def mock_config():
    """Returns a default GVisorConfig."""
    return GVisorConfig()

@pytest.fixture
def sandbox(mock_config):
    """Returns a GVisorSandbox instance with a mock config."""
    return GVisorSandbox(sandbox_id="test-sandbox", config=mock_config)

@pytest.mark.asyncio
async def test_create_writable_filesystem(sandbox, mock_config):
    """Tests that a writable filesystem is created when configured."""
    mock_config.writable_filesystem = True

    with patch("os.makedirs"), \
         patch("builtins.open", mock_open()) as m, \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec, \
         patch.object(sandbox, "_health_check", return_value=True):
        
        mock_proc = AsyncMock()
        mock_proc.wait.return_value = 0
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"", b"")
        
        mock_stdout = MagicMock()
        mock_stdout.at_eof.side_effect = [False, True]
        mock_stdout.read = AsyncMock(return_value=b"")
        mock_proc.stdout = mock_stdout
        
        mock_stderr = MagicMock()
        mock_stderr.at_eof.side_effect = [False, True]
        mock_stderr.read = AsyncMock(return_value=b"")
        mock_proc.stderr = mock_stderr
        
        mock_exec.return_value = mock_proc

        await sandbox.create()

        # Check that the runsc command includes the overlay flag
        run_cmd = mock_exec.call_args[0]
        assert "--overlay2=root:memory" in run_cmd

        # Check that the generated config.json has a readonly root
        bundle_dir = sandbox._bundle_dir
        m.assert_called_once_with(os.path.join(bundle_dir, "config.json"), "w")
        
        written_config_str = "".join(call.args[0] for call in m().write.call_args_list)
        written_config = json.loads(written_config_str)

        assert written_config["root"]["readonly"] is False
        assert written_config["root"]["path"] == "/"

@pytest.mark.asyncio
async def test_create_readonly_filesystem(sandbox, mock_config):
    """Tests that a readonly filesystem is created when configured."""
    mock_config.writable_filesystem = False

    with patch("os.makedirs"), \
         patch("builtins.open", mock_open()) as m, \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec, \
         patch.object(sandbox, "_health_check", return_value=True):
        
        mock_proc = AsyncMock()
        mock_proc.wait.return_value = 0
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"", b"")
        
        mock_stdout = MagicMock()
        mock_stdout.at_eof.side_effect = [False, True]
        mock_stdout.read = AsyncMock(return_value=b"")
        mock_proc.stdout = mock_stdout
        
        mock_stderr = MagicMock()
        mock_stderr.at_eof.side_effect = [False, True]
        mock_stderr.read = AsyncMock(return_value=b"")
        mock_proc.stderr = mock_stderr
        
        mock_exec.return_value = mock_proc

        await sandbox.create()

        # Check that the runsc command does NOT include the overlay flag
        run_cmd = mock_exec.call_args[0]
        assert "--overlay2=root:memory" not in run_cmd

        # Check that the generated config.json has a readonly root
        bundle_dir = sandbox._bundle_dir
        m.assert_called_once_with(os.path.join(bundle_dir, "config.json"), "w")
        
        written_config_str = "".join(call.args[0] for call in m().write.call_args_list)
        written_config = json.loads(written_config_str)

        assert written_config["root"]["readonly"] is True
        assert written_config["root"]["path"] == "/"

def test_build_runsc_cmd_defaults(sandbox):
    """Tests the default runsc command."""
    cmd = sandbox._build_runsc_cmd("run", "my-sandbox")
    assert "--network" in cmd
    assert "host" in cmd
    assert "sudo" not in cmd
    assert "--rootless" not in cmd
    assert "--ignore-cgroups" not in cmd
    assert "--platform" in cmd
    assert "systrap" in cmd

def test_build_runsc_cmd_network_disabled(sandbox, mock_config):
    """Tests that the network flag is correctly set when disabled."""
    mock_config.network = "none"
    cmd = sandbox._build_runsc_cmd("run", "my-sandbox")
    assert "--network" in cmd
    assert "none" in cmd

def test_build_runsc_cmd_no_network_flag(sandbox):
    """Tests that the network flag is not added to non-run commands."""
    cmd = sandbox._build_runsc_cmd("exec", "my-sandbox", "echo", "hello")
    assert "--network" not in cmd

def test_build_runsc_cmd_sudo(sandbox, mock_config):
    """Tests that sudo is used when configured."""
    mock_config.use_sudo = True
    cmd = sandbox._build_runsc_cmd("run", "my-sandbox")
    assert cmd[0] == "sudo"

def test_build_runsc_cmd_rootless(sandbox, mock_config):
    """Tests that the rootless flag is added when configured."""
    mock_config.rootless = True
    cmd = sandbox._build_runsc_cmd("run", "my-sandbox")
    assert "--rootless" in cmd

def test_build_runsc_cmd_ignore_cgroups(sandbox, mock_config):
    """Tests that the ignore-cgroups flag is added when configured."""
    mock_config.ignore_cgroups = True
    cmd = sandbox._build_runsc_cmd("run", "my-sandbox")
    assert "--ignore-cgroups" in cmd

def test_build_runsc_cmd_platform(sandbox, mock_config):
    """Tests that the platform flag is correctly set."""
    mock_config.platform = "kvm"
    cmd = sandbox._build_runsc_cmd("run", "my-sandbox")
    assert "--platform" in cmd
    assert "kvm" in cmd