from fastapi import FastAPI
from .handlers import http, websocket

app = FastAPI()

app.include_router(http.router)
app.include_router(websocket.router)

@app.get("/")
def read_root():
    return {"message": "Server is running"}
