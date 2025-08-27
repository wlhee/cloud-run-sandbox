from fastapi import FastAPI
from .handlers import http, websocket
from .sandbox.manager import manager as sandbox_manager
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events. The ASGI server (e.g., uvicorn)
    is responsible for catching OS signals like SIGTERM and triggering the
    shutdown part of this lifespan context.
    """
    # Code to run on startup can go here
    yield
    # Code to run on shutdown
    await sandbox_manager.delete_all_sandboxes()

app = FastAPI(lifespan=lifespan)

app.include_router(http.router)
app.include_router(websocket.router)

@app.get("/")
def read_root():
    return {"message": "Server is running"}
