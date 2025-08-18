from fastapi import APIRouter
from fastapi.responses import StreamingResponse, PlainTextResponse
from src.sandbox import manager
from typing import Annotated
from fastapi import Body

router = APIRouter()

@router.get("/list", response_class=PlainTextResponse)
async def list_containers():
    output, err = await manager.list_containers()
    if err:
        return PlainTextResponse(err, status_code=500)
    return PlainTextResponse(output)

@router.get("/status", response_class=PlainTextResponse)
async def get_status():
    return PlainTextResponse("Server is running")

@router.get("/suspend/{container_id}", response_class=PlainTextResponse)
async def suspend_container(container_id: str):
    output, err = await manager.suspend_container(container_id)
    if err:
        return PlainTextResponse(err, status_code=500)
    return PlainTextResponse(output)

@router.get("/restore/{container_id}", response_class=PlainTextResponse)
async def restore_container(container_id: str):
    output, err = await manager.resume_container(container_id)
    if err:
        return PlainTextResponse(err, status_code=500)
    return PlainTextResponse(output)

@router.get("/delete/{container_id}", response_class=PlainTextResponse)
async def delete_container(container_id: str):
    output, err = await manager.delete_container(container_id)
    if err:
        return PlainTextResponse(err, status_code=500)
    return PlainTextResponse(output)

@router.post("/execute")
async def execute_code(code: Annotated[str, Body(media_type="text/plain")]):
    return StreamingResponse(manager.execute_code_streaming(code))