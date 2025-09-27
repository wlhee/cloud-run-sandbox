import uvicorn
import os
import logging
from src.server import app
from src.sandbox.manager import manager as sandbox_manager

# ==============================================================================
# Logging Configuration
# ------------------------------------------------------------------------------
# Configure logging to output messages based on the LOG_LEVEL env var.
# ==============================================================================
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)

# ==============================================================================
# Checkpoint and Restore Configuration
# ------------------------------------------------------------------------------
# If a path is provided, the manager will be initialized with checkpointing.
# This path should correspond to a mounted GCS volume in the Cloud Run env.
# ==============================================================================
checkpoint_path = os.environ.get("CHECKPOINT_AND_RESTORE_PATH")
if checkpoint_path:
    logging.info(f"Checkpointing enabled. Path: {checkpoint_path}")
    sandbox_manager.checkpoint_and_restore_path = checkpoint_path

PORT = int(os.environ.get("PORT", 8080))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
