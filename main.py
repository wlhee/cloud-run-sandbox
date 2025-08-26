import uvicorn
import os
import logging
from src.server import app

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

PORT = int(os.environ.get("PORT", 8080))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
