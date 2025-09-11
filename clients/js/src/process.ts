import WebSocket from 'ws';
import { EventEmitter } from 'events';
import { Readable } from 'stream';
import { MessageKey, EventType, SandboxEvent, WebSocketMessage } from './types';

class SandboxStream extends Readable {
  // This is a push-based stream. Data is pushed into it from an external
  // source (the WebSocket message handler) via the `push()` method. The
  // _read() method is a no-op because the stream itself doesn't actively
  // fetch data; it just waits for data to be pushed.
  _read() {}
}

export class SandboxProcess {
  private ws: WebSocket;
  private eventEmitter = new EventEmitter();
  private _startError: Error | null = null;
  private _isDone: boolean = false;

  public readonly stdout: SandboxStream;
  public readonly stderr: SandboxStream;

  constructor(websocket: WebSocket) {
    this.ws = websocket;
    this.stdout = new SandboxStream();
    this.stderr = new SandboxStream();
  }

  public handleMessage(message: WebSocketMessage) {
    if (this._isDone) {
      return; // Don't process any more messages after completion.
    }

    switch (message.event) {
      case EventType.STDOUT:
        this.stdout.push(message.data);
        break;
      
      case EventType.STDERR:
        this.stderr.push(message.data);
        break;

      case EventType.STATUS_UPDATE:
        if (message.status === SandboxEvent.SANDBOX_EXECUTION_RUNNING) {
          this.eventEmitter.emit('started');
        } else if (message.status === SandboxEvent.SANDBOX_EXECUTION_ERROR) {
          this._startError = new Error(message.message || 'Sandbox execution failed');
          this.eventEmitter.emit('started');
        } else if (message.status === SandboxEvent.SANDBOX_EXECUTION_DONE) {
          this._isDone = true;
          this.eventEmitter.emit('done');
        }
        break;
    }
  }

  public async exec(code: string, language: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.eventEmitter.once('started', () => {
        if (this._startError) {
          reject(this._startError);
        } else {
          resolve();
        }
      });

      this.ws.send(JSON.stringify({
        language,
        code,
      }));
    });
  }

  public async wait(): Promise<void> {
    if (this._isDone) {
      return Promise.resolve();
    }
    
    return new Promise((resolve) => {
      this.eventEmitter.once('done', () => {
        this.cleanup();
        resolve();
      });
    });
  }

  private cleanup() {
    this.stdout.push(null);
    this.stderr.push(null);
  }

  public terminate(): void {
    if (!this._isDone) {
      this._isDone = true;
      this.cleanup();
      this.eventEmitter.emit('done');
    }
  }
}
