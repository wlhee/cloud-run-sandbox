/**
 * Copyright 2025 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import WebSocket from 'ws';
import { EventEmitter } from 'events';
import { MessageKey, EventType, SandboxEvent, WebSocketMessage } from './types';
import { SandboxProcess } from './process';
import { Connection, ShouldReconnectCallback, ReconnectInfo } from './connection';

type SandboxState = 'creating' | 'running' | 'closed' | 'failed' | 'checkpointing' | 'checkpointed' | 'restoring' | 'filesystem_snapshotting' | 'reconnecting';

export class Sandbox {
  private connection: Connection;
  private eventEmitter = new EventEmitter();
  private _sandboxId: string | null = null;
  private _creationError: Error | null = null;
  private activeProcess: SandboxProcess | null = null;
  private state: SandboxState = 'creating';
  private _debugEnabled: boolean = false;
  private _debugLabel: string = '';
  private _shouldReconnect: boolean = false;
  private _autoReconnectEnabled: boolean = false;
  private _isCheckpointIntentionally: boolean = false;
  private _url: string = '';
  private _wsOptions?: WebSocket.ClientOptions;
  private stdinBuffer: string[] = [];

  private constructor(connection: Connection, debug: boolean = false, debugLabel: string = '', autoReconnectEnabled: boolean = false) {
    this.connection = connection;
    this._debugEnabled = debug;
    this._debugLabel = debugLabel;
    this._autoReconnectEnabled = autoReconnectEnabled;
    this.connection.on('message', this.handleMessage.bind(this));
    this.connection.on('close', this.handleClose.bind(this));
    this.connection.on('error', this.handleError.bind(this));
    this.connection.on('reopen', this.handleReopen.bind(this));
  }

  public get sandboxId(): string | null {
    return this._sandboxId;
  }

  private logDebugMessage(message: string, ...args: any[]) {
    if (this._debugEnabled) {
      console.log(`[${this._debugLabel}] [DEBUG] ${message}`, ...args);
    }
  }

  private _updateShouldReconnect(status: SandboxEvent) {
    const isFatalError = [
      SandboxEvent.SANDBOX_ERROR,
      SandboxEvent.SANDBOX_NOT_FOUND,
      SandboxEvent.SANDBOX_CREATION_ERROR,
      SandboxEvent.SANDBOX_CHECKPOINT_ERROR,
      SandboxEvent.SANDBOX_RESTORE_ERROR,
      SandboxEvent.SANDBOX_DELETED,
      SandboxEvent.SANDBOX_LOCK_RENEWAL_ERROR,
    ].includes(status);

    if (isFatalError) {
      this._shouldReconnect = false;
    } else if (status === SandboxEvent.SANDBOX_RUNNING) {
      this._shouldReconnect = this._autoReconnectEnabled;
    }
  }

  private handleMessage(data: WebSocket.Data) {
    const message: WebSocketMessage = JSON.parse(data.toString());

    if (message.event != EventType.STDOUT && message.event != EventType.STDERR) {
      this.logDebugMessage('Received message:', message);
    }

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
      this._updateShouldReconnect(message.status);

      switch (message.status) {
        case SandboxEvent.SANDBOX_RUNNING:
          if (this.state === 'reconnecting') {
            this.flushStdinBuffer();
          }
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
    this.logDebugMessage(`Connection closed: code=${code}, reason=${reason ? reason.toString() : 'No reason'}`);
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
    if (this._debugEnabled) {
      console.error(`[${this._debugLabel}] [DEBUG] WebSocket error:`, err);
    }
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

  private handleReopen() {
    this.logDebugMessage('Reconnected. Sending reconnect action.');
    this.connection.send(JSON.stringify({ action: 'reconnect' }));
  }

  public shouldReconnect(code: number, reason: Buffer): boolean {
    const decision = this._shouldReconnect && !this._isCheckpointIntentionally;
    this.logDebugMessage(`Checking if should reconnect: code=${code}, reason=${reason.toString()}, decision=${decision}`);
    if (decision) {
      this.state = 'reconnecting';
    }
    return decision;
  }

  private getReconnectInfo(): ReconnectInfo {
    if (!this._sandboxId) {
      throw new Error('Cannot reconnect without a sandbox ID.');
    }
    const sanitizedUrl = this._url.replace(/\/$/, '');
    const reconnectUrl = `${sanitizedUrl}/attach/${this._sandboxId}`;
    return { url: reconnectUrl, wsOptions: this._wsOptions };
  }

  static create(url: string, options: { idleTimeout?: number, enableSandboxCheckpoint?: boolean, enableSandboxHandoff?: boolean, filesystemSnapshotName?: string, enableDebug?: boolean, debugLabel?: string, wsOptions?: WebSocket.ClientOptions, enableAutoReconnect?: boolean } = {}): Promise<Sandbox> {
    const { idleTimeout = 60, enableSandboxCheckpoint = false, enableSandboxHandoff = false, filesystemSnapshotName, enableDebug = false, debugLabel = '', wsOptions, enableAutoReconnect = false } = options;
    
    const sanitizedUrl = url.replace(/\/$/, '');
    let sandbox: Sandbox;
    const connection = new Connection(
      `${sanitizedUrl}/create`,
      (code, reason) => sandbox.shouldReconnect(code, reason),
      () => sandbox.getReconnectInfo(),
      wsOptions,
      enableDebug,
      debugLabel,
    );
    sandbox = new Sandbox(connection, enableDebug, debugLabel, enableAutoReconnect);
    sandbox._url = url;
    sandbox._wsOptions = wsOptions;

    connection.once('open', () => {
      connection.send(JSON.stringify({
        idle_timeout: idleTimeout,
        enable_checkpoint: enableSandboxCheckpoint,
        enable_sandbox_handoff: enableSandboxHandoff,
        filesystem_snapshot_name: filesystemSnapshotName,
      }));
    });
    
    return new Promise((resolve, reject) => {
      sandbox.eventEmitter.once('created', (createdSandbox) => {
        resolve(createdSandbox);
      });
      
      sandbox.eventEmitter.once('failed', (err) => {
        // On failure, ensure the socket is completely destroyed.
        connection.close();
        reject(err);
      });
    });
  }

  static attach(url: string, sandboxId: string, options: { enableDebug?: boolean, debugLabel?: string, wsOptions?: WebSocket.ClientOptions, enableAutoReconnect?: boolean } = {}): Promise<Sandbox> {
    const { enableDebug = false, debugLabel = '', wsOptions, enableAutoReconnect = false } = options;
    
    const sanitizedUrl = url.replace(/\/$/, '');
    let sandbox: Sandbox;
    const connection = new Connection(
      `${sanitizedUrl}/attach/${sandboxId}`,
      (code, reason) => sandbox.shouldReconnect(code, reason),
      () => sandbox.getReconnectInfo(),
      wsOptions,
      enableDebug,
      debugLabel,
    );
    sandbox = new Sandbox(connection, enableDebug, debugLabel, enableAutoReconnect);
    sandbox._url = url;
    sandbox._wsOptions = wsOptions;
    sandbox._sandboxId = sandboxId;

    return new Promise((resolve, reject) => {
      sandbox.eventEmitter.once('created', (createdSandbox) => {
        resolve(createdSandbox);
      });
      
      sandbox.eventEmitter.once('failed', (err) => {
        // On failure, ensure the socket is completely destroyed.
        connection.close();
        reject(err);
      });
    });
  }

  public checkpoint(): Promise<void> {
    if (this.state !== 'running') {
      return Promise.reject(new Error(`Sandbox is not in a running state. Current state: ${this.state}`));
    }
    this._isCheckpointIntentionally = true;
    this.connection.send(JSON.stringify({ action: 'checkpoint' }));

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

    this.connection.send(JSON.stringify({ action: 'snapshot_filesystem', name }));

    return new Promise((resolve, reject) => {
      this.eventEmitter.once('filesystem_snapshot_created', () => {
        resolve();
      });
      this.eventEmitter.once('filesystem_snapshot_error', (err) => {
        reject(err);
      });
    });
  }

  private flushStdinBuffer() {
    this.logDebugMessage(`Flushing stdin buffer (${this.stdinBuffer.length} messages).`);
    for (const data of this.stdinBuffer) {
      this.connection.send(data);
    }
    this.stdinBuffer = [];
  }

  private sendMessage(data: string) {
    if (this.state === 'reconnecting') {
      try {
        const message = JSON.parse(data);
        if (message.event === 'stdin') {
          this.logDebugMessage('Buffering stdin message while reconnecting:', message.data);
          this.stdinBuffer.push(data);
          return;
        }
      } catch (e) {
        // Not a JSON message, or doesn't have an event property.
        // Let it pass through. This shouldn't happen for stdin.
      }
    }
    this.connection.send(data);
  }

  public async exec(language: string, code: string): Promise<SandboxProcess> {
    if (this.activeProcess) {
      throw new Error('Another process is already running in this sandbox.');
    }
    if (this.state !== 'running') {
      throw new Error(`Sandbox is not in a running state. Current state: ${this.state}`);
    }

    const process = new SandboxProcess(
      this.sendMessage.bind(this),
    );
    this.activeProcess = process;
    
    process['eventEmitter'].once('done', () => {
      this.activeProcess = null;
    });

    await process.exec(language, code);
    return process;
  }

  public terminate() {
    this.connection.close();
  }
}
