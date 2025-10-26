# GEMINI.md

## Project Overview

This project is a web server that executes Python and Bash code in a sandboxed environment on Google Cloud Run. It uses gVisor for sandboxing, which provides a secure isolation layer between the executed code and the host system. The server is built with FastAPI, a modern Python web framework, and it exposes both HTTP and WebSocket endpoints for code execution.

The project also includes a client library in TypeScript for interacting with the server.

## Building and Running

### Server

The server is a Python application built with FastAPI. To run the server locally, you need to have Python and the required dependencies installed.

1.  **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

2.  **Run the server:**

    ```bash
    uvicorn main:app --host 0.0.0.0 --port 8080
    ```

### Client

The project includes a client library in TypeScript.

**TypeScript Client:**

The TypeScript client can be used to interact with the server. See `example/client_example.ts` for a detailed example.

## Development Conventions

*   **Server:** The server is written in Python using the FastAPI framework.
*   **Client:** The client library is written in TypeScript.
*   **Sandboxing:** The project uses gVisor for sandboxing.
*   **Testing:** The project includes unit and integration tests. To run the tests, you can use `pytest`:

    ```bash
    pytest
    ```
*   **Git:** Do not use command substitution using `$( )`, `` ` `` , `<( )`, or `>( )` in git commit messages.

## Key Files

*   `main.py`: The entry point for the server application.
*   `src/server.py`: The main FastAPI application.
*   `src/handlers/http.py`: The HTTP request handlers.
*   `src/handlers/websocket.py`: The WebSocket request handlers.
*   `src/sandbox/manager.py`: The sandbox manager, which manages the lifecycle of sandboxes.
*   `src/sandbox/gvisor.py`: The gVisor sandbox implementation.
*   `clients/js/`: The TypeScript client library.
*   `example/`: Example client usage.
