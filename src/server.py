from fastapi import FastAPI
from .handlers import http, websocket
from .sandbox.manager import SandboxManager
from .sandbox.lock.factory import LockFactory
from .sandbox.config import GCSConfig
from contextlib import asynccontextmanager
import logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events.
    """
    # --- Startup ---
    # 1. Load GCS config from environment
    gcs_config = GCSConfig.from_env()
    lock_factory = None
    
    # 2. If a metadata bucket is configured, create a real GCS lock factory
    if gcs_config.metadata_bucket:
        logging.info(f"GCS persistence enabled (bucket: {gcs_config.metadata_bucket}).")
        lock_factory = LockFactory(gcs_bucket_name=gcs_config.metadata_bucket)
    else:
        logging.info("GCS persistence not configured. Using in-memory lock factory.")
        lock_factory = LockFactory()

    # 3. Create and configure the sandbox manager and enable idle cleanup
    manager = SandboxManager(gcs_config=gcs_config, lock_factory=lock_factory)
    manager.enable_idle_cleanup()

    # 4. Inject the configured manager into the handler modules
    http.manager = manager
    websocket.manager = manager
    
    yield
    
    # --- Shutdown ---
    await manager.delete_all_sandboxes()

app = FastAPI(lifespan=lifespan)

app.include_router(http.router)
app.include_router(websocket.router)

@app.get("/")
def read_root():
    return {"message": "Server is running"}
