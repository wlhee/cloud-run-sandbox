from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import StreamingResponse, PlainTextResponse
from typing import Annotated
import asyncio
import subprocess
import os
import json
import uuid

# ==============================================================================
# Temporary gVisor Sandbox Logic
# ------------------------------------------------------------------------------
# The following functions contain the basic logic for interacting with gVisor
# sandboxes via the 'runsc' command. This is a temporary home for this logic.
# In the future, this will be refactored into the SandboxManager to provide a
# unified interface for both stateful (WebSocket) and stateless (HTTP) sandboxes.
# ==============================================================================

async def list_containers():
    """Lists all running gVisor containers."""
    proc = await asyncio.create_subprocess_exec(
        "runsc", "list",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return None, stderr.decode()
    return stdout.decode(), None

async def suspend_container(container_id):
    """Suspends a running gVisor container."""
    proc = await asyncio.create_subprocess_exec(
        "runsc", "pause", container_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return None, stderr.decode()
    return f"App {container_id} suspended", None

async def resume_container(container_id):
    """Resumes a suspended gVisor container."""
    proc = await asyncio.create_subprocess_exec(
        "runsc", "resume", container_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return None, stderr.decode()
    return f"App {container_id} restored", None

async def delete_container(container_id):
    """Deletes a gVisor container."""
    proc = await asyncio.create_subprocess_exec(
        "runsc", "delete", container_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return None, stderr.decode()
    return f"App {container_id} deleted", None

async def execute_code_streaming(code: str):
    """
    Executes Python code in a new gVisor sandbox and yields the output lines.
    """
    temp_dir = "/tmp"
    os.makedirs(temp_dir, exist_ok=True)
    
    temp_filename = f"temp_code-{uuid.uuid4()}.py"
    temp_filepath = os.path.join(temp_dir, temp_filename)
    
    with open(temp_filepath, "w") as f:
        f.write(code)
        
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
        process = await asyncio.create_subprocess_exec(
            *run_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        async def stream_lines(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                yield line

        # Interleave stdout and stderr by processing them concurrently
        stdout_task = asyncio.create_task(stream_lines(process.stdout).__anext__())
        stderr_task = asyncio.create_task(stream_lines(process.stderr).__anext__())
        
        while not stdout_task.done() or not stderr_task.done():
            done, pending = await asyncio.wait(
                [stdout_task, stderr_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                try:
                    line = task.result()
                    yield line
                    if task is stdout_task:
                        stdout_task = asyncio.create_task(stream_lines(process.stdout).__anext__())
                    else:
                        stderr_task = asyncio.create_task(stream_lines(process.stderr).__anext__())
                except StopAsyncIteration:
                    pass # This stream is done

        await process.wait()

    except Exception as e:
        yield f"Server error: {e}\n".encode('utf-8')
    finally:
        if process and process.returncode is None:
            process.terminate()
            await process.wait()
            print(f"Process {container_id} terminated.")

# ==============================================================================
# FastAPI Route Handlers
# ==============================================================================

router = APIRouter()

@router.get("/status", response_class=PlainTextResponse)
async def get_status():
    return PlainTextResponse("Server is running")

@router.get("/containers")
async def list_all_containers():
    """Lists all running gVisor containers."""
    output, error = await list_containers()
    if error:
        raise HTTPException(status_code=500, detail=error)
    return {"containers": output}

@router.post("/containers/{container_id}/suspend")
async def suspend(container_id: str):
    """Suspends a running gVisor container."""
    output, error = await suspend_container(container_id)
    if error:
        raise HTTPException(status_code=500, detail=error)
    return {"status": output}

@router.post("/containers/{container_id}/resume")
async def resume(container_id: str):
    """Resumes a suspended gVisor container."""
    output, error = await resume_container(container_id)
    if error:
        raise HTTPException(status_code=500, detail=error)
    return {"status": output}

@router.delete("/containers/{container_id}")
async def delete(container_id: str):
    """Deletes a gVisor container."""
    output, error = await delete_container(container_id)
    if error:
        raise HTTPException(status_code=500, detail=error)
    return {"status": output}

@router.post("/execute")
async def execute_code(code: Annotated[str, Body(media_type="text/plain")]):
    """Executes Python code in a new gVisor sandbox and streams the output."""
    return StreamingResponse(execute_code_streaming(code), media_type="text/plain")
