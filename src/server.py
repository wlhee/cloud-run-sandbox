from fastapi import FastAPI
from .handlers import http

app = FastAPI()

app.include_router(http.router)

@app.get("/")
def read_root():
    return {"message": "Server is running"}
