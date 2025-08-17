import subprocess
import os
import json
import uuid
import select

def list_containers():
    """Lists all running gVisor containers."""
    try:
        result = subprocess.run(["runsc", "list"], check=True, capture_output=True, text=True)
        return result.stdout, None
    except Exception as e:
        return None, str(e)

def suspend_container(container_id):
    """Suspends a running gVisor container."""
    try:
        subprocess.run(["runsc", "pause", container_id], check=True)
        return f"App {container_id} suspended", None
    except Exception as e:
        return None, str(e)

def resume_container(container_id):
    """Resumes a suspended gVisor container."""
    try:
        subprocess.run(["runsc", "resume", container_id], check=True)
        return f"App {container_id} restored", None
    except Exception as e:
        return None, str(e)

def delete_container(container_id):
    """Deletes a gVisor container."""
    try:
        subprocess.run(["runsc", "delete", container_id], check=True)
        return f"App {container_id} deleted", None
    except Exception as e:
        return None, str(e)

def execute_code(post_data, wfile):
    """
    Executes Python code in a new gVisor sandbox and streams the output.
    """
    temp_dir = "/tmp"
    os.makedirs(temp_dir, exist_ok=True)
    
    temp_filename = f"temp_code-{uuid.uuid4()}.py"
    temp_filepath = os.path.join(temp_dir, temp_filename)
    
    with open(temp_filepath, "wb") as f:
        f.write(post_data)
        
    container_id = f"exec-{uuid.uuid4()}"
    bundle_dir = f"/tmp/runsc_bundle_{container_id}"
    os.makedirs(bundle_dir, exist_ok=True)

    config = {
        "ociVersion": "1.0.0",
        "process": {
            "user": {"uid": 0, "gid": 0},
            "args": ["python3", temp_filepath],
            "env": [
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "TERM=xterm",
                f"CONTAINER_ID={container_id}"
            ],
            "cwd": "/",
            "capabilities": {
                "bounding": ["CAP_AUDIT_WRITE", "CAP_KILL"],
                "effective": ["CAP_AUDIT_WRITE", "CAP_KILL"],
                "inheritable": ["CAP_AUDIT_WRITE", "CAP_KILL"],
                "permitted": ["CAP_AUDIT_WRITE", "CAP_KILL"],
            },
            "rlimits": [{"type": "RLIMIT_NOFILE", "hard": 1024, "soft": 1024}],
        },
        "root": {"path": "/", "readonly": False},
        "hostname": "runsc",
        "mounts": [
            {"destination": "/proc", "type": "proc", "source": "proc"},
            {"destination": "/dev", "type": "tmpfs", "source": "tmpfs"},
            {"destination": "/sys", "type": "sysfs", "source": "sysfs"},
        ],
        "linux": {
            "namespaces": [
                {"type": "pid"},
                {"type": "network"},
                {"type": "ipc"},
                {"type": "uts"},
                {"type": "mount"},
            ],
            "resources": {"memory": {"limit": 2147483648}},
        },
    }
    with open(os.path.join(bundle_dir, "config.json"), "w") as f:
        json.dump(config, f, indent=4)

    process = None
    try:
        run_cmd = ["runsc", "--network=host", "run", "-bundle", bundle_dir, container_id]
        process = subprocess.Popen(run_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        reads = [process.stdout, process.stderr]

        while reads:
            readable, _, _ = select.select(reads, [], [])
            
            for fd in readable:
                line = fd.readline()
                if line:
                    wfile.write(line)
                else:
                    reads.remove(fd)
        return None # Success
    except BrokenPipeError:
        print(f"Client disconnected, terminating process {container_id}")
        return "Client disconnected"
    except Exception as e:
        return f"Server error: {e}"
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait()
            print(f"Process {container_id} terminated.")
