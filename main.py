import uvicorn
import os
from src.server import app

PORT = int(os.environ.get("PORT", 8080))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
