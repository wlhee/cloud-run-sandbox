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
# GCS Persistence Configuration
# ------------------------------------------------------------------------------
# If any GCS env vars are set, the manager will be initialized with the
# corresponding persistence and locking configuration.
# ==============================================================================
from dataclasses import asdict
from src.sandbox.config import GCSConfig

gcs_config = GCSConfig.from_env()
if any(asdict(gcs_config).values()):
    logging.info("GCS persistence enabled.")
    sandbox_manager.gcs_config = gcs_config

PORT = int(os.environ.get("PORT", 8080))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
