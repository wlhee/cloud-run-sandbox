import WebSocket from 'ws';
import { EventEmitter } from 'events';
import { MessageKey, EventType, SandboxEvent, WebSocketMessage } from './types';
import { SandboxProcess } from './process';

type SandboxState = 'creating' | 'running' | 'closed' | 'failed' | 'checkpointing' | 'checkpointed' | 'restoring' | 'filesystem_snapshotting';

export class Sandbox {
  private ws: WebSocket;
  private eventEmitter = new EventEmitter();
  private _sandboxId: string | null = null;
  private _creationError: Error | null = null;
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

    // Process-specific events are always forwarded
    if (
      message.event === EventType.STDOUT ||
      message.event === EventType.STDERR ||
      (message.event === EventType.STATUS_UPDATE &&
        message.status &&
        message.status.startsWith('SANDBOX_EXECUTION_') &&
        message.status !== SandboxEvent.SANDBOX_EXECUTION_IN_PROGRESS_ERROR)
    ) {
      if (this.activeProcess) {
        this.activeProcess.handleMessage(message);
      }
      return;
    }

    // Handle sandbox lifecycle events
    if (message.event === EventType.SANDBOX_ID) {
      this._sandboxId = message.sandbox_id;
      return;
    }

    if (message.event === EventType.STATUS_UPDATE) {
      switch (message.status) {
        case SandboxEvent.SANDBOX_RUNNING:
          this.state = 'running';
          this.eventEmitter.emit('created', this);
          break;
        case SandboxEvent.SANDBOX_CREATION_ERROR:
          if (this.state === 'creating') {
            this.state = 'failed';
            this._creationError = new Error(message.message || message.status);
            this.eventEmitter.emit('failed', this._creationError);
          }
          break;
        case SandboxEvent.SANDBOX_CHECKPOINTING:
          this.state = 'checkpointing';
          break;
        case SandboxEvent.SANDBOX_CHECKPOINTED:
          this.state = 'checkpointed';
          this.eventEmitter.emit('checkpointed');
          break;
        case SandboxEvent.SANDBOX_CHECKPOINT_ERROR:
          this.state = 'failed'; // This is a fatal error for the session.
          this.eventEmitter.emit('checkpoint_error', new Error(message.message || message.status));
          break;
        case SandboxEvent.SANDBOX_EXECUTION_IN_PROGRESS_ERROR:
          this.state = 'running'; // Checkpoint failed, back to running
          this.eventEmitter.emit('checkpoint_error', new Error(message.message || message.status));
          break;
        case SandboxEvent.SANDBOX_RESTORING:
          this.state = 'restoring';
          break;
        case SandboxEvent.SANDBOX_RESTORE_ERROR:
          this.state = 'failed';
          this._creationError = new Error(message.message || message.status);
          this.eventEmitter.emit('failed', this._creationError);
          break;
        case SandboxEvent.SANDBOX_NOT_FOUND:
          this.state = 'failed';
          this._creationError = new Error(message.message || message.status);
          this.eventEmitter.emit('failed', this._creationError);
          break;
        case SandboxEvent.SANDBOX_FILESYSTEM_SNAPSHOT_CREATING:
          this.state = 'filesystem_snapshotting';
          break;
        case SandboxEvent.SANDBOX_FILESYSTEM_SNAPSHOT_CREATED:
          this.state = 'running';
          this.eventEmitter.emit('filesystem_snapshot_created');
          break;
        case SandboxEvent.SANDBOX_FILESYSTEM_SNAPSHOT_ERROR:
          this.state = 'running';
          this.eventEmitter.emit('filesystem_snapshot_error', new Error(message.message || message.status));
          break;
      }
      return;
    }
  }

  private handleClose(code: number, reason: Buffer) {
    if (this.state === 'creating' || this.state === 'restoring') {
      this.state = 'failed';
      const err = new Error(`Connection closed during creation/restoration: code=${code}`);
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
    if (this.state === 'creating' || this.state === 'restoring') {
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

  static create(url: string, options: { idleTimeout?: number, enableSandboxCheckpoint?: boolean, filesystemSnapshotName?: string, wsOptions?: WebSocket.ClientOptions } = {}): Promise<Sandbox> {
    const { idleTimeout = 60, enableSandboxCheckpoint = false, filesystemSnapshotName, wsOptions } = options;
    
    const sanitizedUrl = url.replace(/\/$/, '');
    const ws = new WebSocket(`${sanitizedUrl}/create`, wsOptions);
    const sandbox = new Sandbox(ws);

    ws.on('open', () => {
      ws.send(JSON.stringify({
        idle_timeout: idleTimeout,
        enable_checkpoint: enableSandboxCheckpoint,
        filesystem_snapshot_name: filesystemSnapshotName,
      }));
    });
    
    return new Promise((resolve, reject) => {
      sandbox.eventEmitter.once('created', (createdSandbox) => {
        resolve(createdSandbox);
      });
      
      sandbox.eventEmitter.once('failed', (err) => {
        // On failure, ensure the socket is completely destroyed.
        if (ws.readyState !== WebSocket.CLOSED && ws.readyState !== WebSocket.CLOSING) {
          ws.terminate();
        }
        reject(err);
      });
    });
  }

  static attach(url: string, sandboxId: string, options: { wsOptions?: WebSocket.ClientOptions } = {}): Promise<Sandbox> {
    const { wsOptions } = options;
    
    const sanitizedUrl = url.replace(/\/$/, '');
    const ws = new WebSocket(`${sanitizedUrl}/attach/${sandboxId}`, wsOptions);
    const sandbox = new Sandbox(ws);
    sandbox._sandboxId = sandboxId;

    return new Promise((resolve, reject) => {
      sandbox.eventEmitter.once('created', (createdSandbox) => {
        resolve(createdSandbox);
      });
      
      sandbox.eventEmitter.once('failed', (err) => {
        // On failure, ensure the socket is completely destroyed.
        if (ws.readyState !== WebSocket.CLOSED && ws.readyState !== WebSocket.CLOSING) {
          ws.terminate();
        }
        reject(err);
      });
    });
  }

  public checkpoint(): Promise<void> {
    if (this.state !== 'running') {
      return Promise.reject(new Error(`Sandbox is not in a running state. Current state: ${this.state}`));
    }

    this.ws.send(JSON.stringify({ action: 'checkpoint' }));

    return new Promise((resolve, reject) => {
      this.eventEmitter.once('checkpointed', () => {
        resolve();
      });
      this.eventEmitter.once('checkpoint_error', (err) => {
        reject(err);
      });
    });
  }

  public snapshotFilesystem(name: string): Promise<void> {
    if (this.state !== 'running') {
      return Promise.reject(new Error(`Sandbox is not in a running state. Current state: ${this.state}`));
    }

    this.ws.send(JSON.stringify({ action: 'snapshot_filesystem', name }));

    return new Promise((resolve, reject) => {
      this.eventEmitter.once('filesystem_snapshot_created', () => {
        resolve();
      });
      this.eventEmitter.once('filesystem_snapshot_error', (err) => {
        reject(err);
      });
    });
  }

  public async exec(language: string, code: string): Promise<SandboxProcess> {
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

    await process.exec(language, code);
    return process;
  }

  public terminate() {
    if (this.ws.readyState === WebSocket.OPEN) {
      this.ws.close();
    }
  }
}
