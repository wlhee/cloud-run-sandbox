import asyncio
import websockets
import json

PORT = 8080

async def test_workflow():
    """
    A simple client script to manually test the server's workflow.
    """
    uri_create = f"ws://localhost:{PORT}/create"
    sandbox_id = None

    try:
        print("--- Testing /create endpoint ---")
        async with websockets.connect(uri_create) as websocket:
            print("Connection to /create successful.")

            message = await websocket.recv()
            data = json.loads(message)
            print(f"S: {data}")
            assert data["status"] == "CREATING"

            message = await websocket.recv()
            data = json.loads(message)
            print(f"S: {data}")
            assert data["event"] == "created"
            sandbox_id = data.get("sandbox_id")
            assert sandbox_id is not None

            message = await websocket.recv()
            data = json.loads(message)
            print(f"S: {data}")
            assert data["status"] == "RUNNING"

            print("\nC: Sending 'hello'...")
            await websocket.send("hello")
            response = await websocket.recv()
            print(f"S: {json.loads(response)}")
            print("--- /create test successful ---")

        print(f"\n--- Attaching to sandbox: {sandbox_id} ---")
        uri_attach = f"ws://localhost:{PORT}/attach/{sandbox_id}"
        async with websockets.connect(uri_attach) as websocket:
            print("Connection to /attach successful.")
            
            message = await websocket.recv()
            data = json.loads(message)
            print(f"S: {data}")
            assert data["status"] == "RUNNING"

            print("\nC: Sending 'world'...")
            await websocket.send("world")
            response = await websocket.recv()
            print(f"S: {json.loads(response)}")
            print("--- /attach test successful ---")

        print("\n--- Workflow test completed successfully! ---")

    except Exception as e:
        print(f"\n--- An error occurred: {e} ---")


if __name__ == "__main__":
    asyncio.run(test_workflow())
