from fastapi import APIRouter, HTTPException, Body, BackgroundTasks
from fastapi.responses import StreamingResponse, PlainTextResponse
from typing import Annotated
from src.sandbox.manager import manager as sandbox_manager
from src.sandbox.types import CodeLanguage
from src.sandbox.interface import SandboxStreamClosed
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

async def execute_code_streaming(language: CodeLanguage, code: str, background_tasks: BackgroundTasks):
    """
    Executes code in a new sandbox and yields the output.
    """
    sandbox = None
    try:
        sandbox = await sandbox_manager.create_sandbox()
        await sandbox.execute(language, code)
        
        async for event in sandbox.connect():
            yield event["data"].encode('utf-8')

    except SandboxStreamClosed:
        print("Received SandboxStreamClosed exception.")
        pass # This is the expected way for the stream to end.
    except Exception as e:
        yield f"Server error: {e}\n".encode('utf-8')
    finally:
        if sandbox:
            background_tasks.add_task(sandbox_manager.delete_sandbox, sandbox.sandbox_id)

# ==============================================================================
# FastAPI Route Handlers
# ==============================================================================

router = APIRouter()

@router.get("/status", response_class=PlainTextResponse)
async def get_status():
    return PlainTextResponse("Server is running")

@router.get("/list")
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
async def execute_code(
    background_tasks: BackgroundTasks,
    code: Annotated[str, Body(media_type="text/plain")],
    language: CodeLanguage = CodeLanguage.PYTHON
):
    """
    Executes code in a new gVisor sandbox and streams the output.
    The sandbox is deleted in a background task after the stream is closed.
    """
    return StreamingResponse(execute_code_streaming(language, code, background_tasks), media_type="text/plain")
