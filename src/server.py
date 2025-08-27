from fastapi import FastAPI
from .handlers import http, websocket
from .sandbox.manager import manager as sandbox_manager
import signal
import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(
        signal.SIGTERM,
        lambda: asyncio.create_task(sandbox_manager.delete_all_sandboxes())
    )
    yield
    # Shutdown
    await sandbox_manager.delete_all_sandboxes()

app = FastAPI(lifespan=lifespan)

app.include_router(http.router)
app.include_router(websocket.router)

@app.get("/")
def read_root():
    return {"message": "Server is running"}
