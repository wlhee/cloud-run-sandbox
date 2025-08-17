import asyncio
import websockets
from . import handlers

PORT = 8080

async def main():
    """
    Starts the WebSocket server.
    """
    async with websockets.serve(handlers.handler, "0.0.0.0", PORT):
        print(f"Server started on port {PORT}")
        await asyncio.Future()  # run forever

def run():
    """
    Entry point to run the server.
    """
    asyncio.run(main())