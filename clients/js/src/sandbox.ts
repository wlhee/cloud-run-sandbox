import WebSocket from 'ws';
import { EventEmitter } from 'events';
import { MessageKey, EventType, SandboxEvent, WebSocketMessage } from './types';
import { SandboxProcess } from './process';

type SandboxState = 'creating' | 'running' | 'closed' | 'failed';

export class Sandbox {
  private ws: WebSocket;
  private eventEmitter = new EventEmitter();
  private _sandboxId: string | null = null;
  private _creationError: Error | null = null;
  private _isRunning: boolean = false;
  private activeProcess: SandboxProcess | null = null;
  private state: SandboxState = 'creating';

  private constructor(websocket: WebSocket) {
    this.ws = websocket;
    this.ws.on('message', this.handleMessage.bind(this));
    this.ws.on('close', this.handleClose.bind(this));
    this.ws.on('error', this.handleError.bind(this));
  }

  public get sandboxId(): string | null {
    return this._sandboxId;
  }

  private handleMessage(data: WebSocket.Data) {
    const message: WebSocketMessage = JSON.parse(data.toString());
    console.log('[SANDBOX] handleMessage received:', message);

    // Process-specific events are always forwarded
    if (
      message.event === EventType.STDOUT ||
      message.event === EventType.STDERR ||
      (message.event === EventType.STATUS_UPDATE &&
        message.status &&
        message.status.startsWith('sandbox_execution_'))
    ) {
      if (this.activeProcess) {
        this.activeProcess.handleMessage(message);
      } else {
        console.warn('Received process message without an active process:', message);
      }
      return;
    }

    // Handle sandbox lifecycle events
    if (message.event === EventType.SANDBOX_ID) {
      this._sandboxId = message.sandbox_id;
      if (this._isRunning) {
        this.state = 'running';
        this.eventEmitter.emit('created', this);
      }
      return;
    }

    if (message.event === EventType.STATUS_UPDATE) {
      switch (message.status) {
        case SandboxEvent.SANDBOX_RUNNING:
          this._isRunning = true;
          if (this._sandboxId) {
            this.state = 'running';
            this.eventEmitter.emit('created', this);
          }
          break;
        case SandboxEvent.SANDBOX_CREATION_ERROR:
          if (this.state === 'creating') {
            this.state = 'failed';
            this._creationError = new Error(message.message || message.status);
            this.eventEmitter.emit('failed', this._creationError);
          }
          break;
      }
      return;
    }
    
    console.warn('Unhandled sandbox event:', message);
  }

  private handleClose(code: number, reason: Buffer) {
    const reasonStr = reason ? reason.toString() : '';
    console.log(`[SANDBOX] WebSocket closed: code=${code}, reason=${reasonStr}`);
    if (this.state === 'creating') {
      console.log('[SANDBOX] handleClose emitting failed');
      this.state = 'failed';
      const err = new Error(`Connection closed during creation: code=${code}`);
      this.eventEmitter.emit('failed', err);
    } else {
      this.state = 'closed';
    }
    
    if (this.activeProcess) {
      this.activeProcess.terminate();
      this.activeProcess = null;
    }
  }

  private handleError(err: Error) {
    console.error('[SANDBOX] WebSocket error:', err);
    if (this.state === 'creating') {
      console.log('[SANDBOX] handleError emitting failed');
      this.state = 'failed';
      this.eventEmitter.emit('failed', err);
    }
    
    if (this.activeProcess) {
      this.activeProcess.terminate();
      this.activeProcess = null;
    }
    // In the 'running' state, you might want to emit a general error
    // for the user to handle, e.g., this.eventEmitter.emit('error', err);
  }

  static create(url: string, options: { idleTimeout?: number, wsOptions?: WebSocket.ClientOptions } = {}): Promise<Sandbox> {
    const { idleTimeout = 60, wsOptions } = options;
    console.log('[SANDBOX] create called');
    
    const ws = new WebSocket(`${url}/create`, wsOptions);
    const sandbox = new Sandbox(ws);

    ws.on('open', () => {
      console.log('[SANDBOX] ws open');
      ws.send(JSON.stringify({ idle_timeout: idleTimeout }));
    });
    
    return new Promise((resolve, reject) => {
      sandbox.eventEmitter.once('created', (createdSandbox) => {
        console.log('[PROMISE] "created" event received. Resolving.');
        resolve(createdSandbox);
      });
      
      sandbox.eventEmitter.once('failed', (err) => {
        console.log('[PROMISE] "failed" event received. Terminating and rejecting.');
        // On failure, ensure the socket is completely destroyed.
        if (ws.readyState !== WebSocket.CLOSED && ws.readyState !== WebSocket.CLOSING) {
          ws.terminate();
        }
        reject(err);
      });
    });
  }

  public async exec(code: string, language: string): Promise<SandboxProcess> {
    if (this.activeProcess) {
      throw new Error('Another process is already running in this sandbox.');
    }
    if (this.state !== 'running') {
      throw new Error(`Sandbox is not in a running state. Current state: ${this.state}`);
    }

    const process = new SandboxProcess(this.ws);
    this.activeProcess = process;
    
    process['eventEmitter'].once('done', () => {
      this.activeProcess = null;
    });

    await process.exec(code, language);
    return process;
  }

  public terminate() {
    if (this.ws.readyState === WebSocket.OPEN) {
      this.ws.close();
    }
  }
}
