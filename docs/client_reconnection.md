# Client Reconnection

This document describes the client reconnection feature, which allows a client to automatically reconnect to a sandbox session if the WebSocket connection is unexpectedly closed.

## Overview

The client reconnection feature is designed to improve the resilience of the sandbox sessions. If a client's WebSocket connection is dropped due to a network issue or other transient failure, the client will attempt to automatically reconnect to the same sandbox session, preserving the state of the sandbox and any running processes.

## The `Connection` Class

The `Connection` class in `clients/js/src/connection.ts` is a wrapper around the `ws` WebSocket library that provides the core reconnection logic. It handles the following:

- **Automatic Reconnection:** When a WebSocket connection is closed, the `Connection` class consults a `shouldReconnect` callback to determine if it should attempt to reconnect.
- **Reconnection Information:** If a reconnection is necessary, the `Connection` class calls a `getReconnectInfo` callback to get the URL and options for the new connection. This allows the client to reconnect to the same sandbox session.
- **Reopen Event:** When a connection is re-established, the `Connection` class emits a `reopen` event, which the `Sandbox` class uses to send a `reconnect` action to the server.

## The `Sandbox` Class

The `Sandbox` class in `clients/js/src/sandbox.ts` is updated to use the `Connection` class and manage the reconnection state.

### `reconnecting` State

A new `reconnecting` state has been added to the `Sandbox` class. When the `shouldReconnect` callback is called and returns `true`, the sandbox's state is set to `reconnecting`. This prevents any new operations from being started until the connection is re-established.

### stdin Buffering

While the sandbox is in the `reconnecting` state, any stdin messages sent to a running process are buffered in a `stdinBuffer`. Once the connection is re-established and the sandbox returns to the `running` state, the buffered stdin messages are flushed to the server, ensuring that no user input is lost.

## Server-Side Handling

The `WebsocketHandler` in `src/handlers/websocket.py` has a new `reconnect_and_stream` method to handle the `reconnect` action from the client. When this action is received, the server resumes streaming any buffered output from the sandbox to the newly connected client.
