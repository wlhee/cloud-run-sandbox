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

import { Sandbox } from '../src/sandbox';
import WebSocket from 'ws';
import { EventEmitter } from 'events';
import { jest } from '@jest/globals';
import { MessageKey, EventType, SandboxEvent } from '../src/types';

// Mock the WebSocket class
jest.mock('ws');

const MockWebSocket = WebSocket as jest.MockedClass<typeof WebSocket>;

describe('Sandbox', () => {
  let mockWsInstance: EventEmitter & { send: jest.Mock; close: jest.Mock; terminate: jest.Mock; readyState: number; };

  beforeEach(() => {
    // Create a fresh mock instance for each test
    mockWsInstance = new EventEmitter() as any;
    mockWsInstance.send = jest.fn();
    mockWsInstance.close = jest.fn();
    mockWsInstance.terminate = jest.fn();
    mockWsInstance.readyState = 1; // WebSocket.OPEN

    // Make the constructor return our mock instance
    MockWebSocket.mockImplementation(() => mockWsInstance as any);
  });

  it('should create and terminate a sandbox successfully', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    
    mockWsInstance.emit('open');

    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));

    const sandbox = await createPromise;

    expect(sandbox).toBeInstanceOf(Sandbox);
    expect(sandbox.sandboxId).toBe('test-id');
    expect(mockWsInstance.send).toHaveBeenCalledWith(JSON.stringify({
      idle_timeout: 60,
      enable_checkpoint: false,
      enable_sandbox_handoff: false,
      filesystem_snapshot_name: undefined,
    }));

    sandbox.terminate();
    expect(mockWsInstance.close).toHaveBeenCalled();
  });

  it('should create a sandbox with checkpointing enabled', async () => {
    const createPromise = Sandbox.create('ws://test-url', { enableSandboxCheckpoint: true });
    
    mockWsInstance.emit('open');

    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));

    const sandbox = await createPromise;

    expect(sandbox).toBeInstanceOf(Sandbox);
    expect(sandbox.sandboxId).toBe('test-id');
    expect(mockWsInstance.send).toHaveBeenCalledWith(JSON.stringify({
      idle_timeout: 60,
      enable_checkpoint: true,
      enable_sandbox_handoff: false,
      filesystem_snapshot_name: undefined,
    }));

    sandbox.terminate();
    expect(mockWsInstance.close).toHaveBeenCalled();
  });

  it('should create a sandbox with handoff enabled', async () => {
    const createPromise = Sandbox.create('ws://test-url', { enableSandboxHandoff: true });
    
    mockWsInstance.emit('open');

    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));

    const sandbox = await createPromise;

    expect(sandbox).toBeInstanceOf(Sandbox);
    expect(sandbox.sandboxId).toBe('test-id');
    expect(mockWsInstance.send).toHaveBeenCalledWith(JSON.stringify({
      idle_timeout: 60,
      enable_checkpoint: false,
      enable_sandbox_handoff: true,
      filesystem_snapshot_name: undefined,
    }));

    sandbox.terminate();
    expect(mockWsInstance.close).toHaveBeenCalled();
  });

  it('should log debug messages with label when enabled', async () => {
    const consoleLogSpy = jest.spyOn(console, 'log').mockImplementation(() => {});
    const createPromise = Sandbox.create('ws://test-url', { enableDebug: true, debugLabel: 'TestSandbox' });
    
    mockWsInstance.emit('open');

    const sandboxIdMessage = {
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    };
    mockWsInstance.emit('message', JSON.stringify(sandboxIdMessage));
    
    const runningMessage = {
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    };
    mockWsInstance.emit('message', JSON.stringify(runningMessage));

    await createPromise;

    expect(consoleLogSpy).toHaveBeenCalledWith('[TestSandbox] [DEBUG] Received message:', sandboxIdMessage);
    expect(consoleLogSpy).toHaveBeenCalledWith('[TestSandbox] [DEBUG] Received message:', runningMessage);

    consoleLogSpy.mockRestore();
  });

  it('should create a sandbox with a filesystem snapshot', async () => {
    const createPromise = Sandbox.create('ws://test-url', { filesystemSnapshotName: 'my-snapshot' });
    
    mockWsInstance.emit('open');

    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));

    const sandbox = await createPromise;

    expect(sandbox).toBeInstanceOf(Sandbox);
    expect(sandbox.sandboxId).toBe('test-id');
    expect(mockWsInstance.send).toHaveBeenCalledWith(JSON.stringify({
      idle_timeout: 60,
      enable_checkpoint: false,
      enable_sandbox_handoff: false,
      filesystem_snapshot_name: 'my-snapshot',
    }));

    sandbox.terminate();
    expect(mockWsInstance.close).toHaveBeenCalled();
  });

  it('should successfully checkpoint a sandbox and prevent further execution', async () => {
    const createPromise = Sandbox.create('ws://test-url', { enableSandboxCheckpoint: true });
    mockWsInstance.emit('open');
    mockWsInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));
    const sandbox = await createPromise;

    const checkpointPromise = sandbox.checkpoint();

    // Simulate server responses
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_CHECKPOINTING' }));
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_CHECKPOINTED' }));

    await expect(checkpointPromise).resolves.toBeUndefined();

    // Verify that exec fails after checkpointing
    await expect(sandbox.exec('bash', 'echo "hello"')).rejects.toThrow('Sandbox is not in a running state. Current state: checkpointed');
  });

  it('should reject creation on server error and terminate the socket', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockWsInstance.emit('open');

    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_CREATION_ERROR,
      [MessageKey.MESSAGE]: 'Creation failed',
    }));

    await expect(createPromise).rejects.toThrow('Creation failed');
    expect(mockWsInstance.terminate).toHaveBeenCalled();
  });

  it('should reject creation on connection error and terminate the socket', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    const error = new Error('Connection error');
    mockWsInstance.emit('error', error);

    await expect(createPromise).rejects.toThrow('Connection error');
    expect(mockWsInstance.terminate).toHaveBeenCalled();
  });

  it('should reject creation if connection closes prematurely and terminate the socket', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockWsInstance.emit('open');
    mockWsInstance.emit('close');

    await expect(createPromise).rejects.toThrow('Connection closed during creation/restoration: code=undefined');
    expect(mockWsInstance.terminate).toHaveBeenCalled();
  });

  it('should reject only once and terminate if error and close are both emitted', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    const error = new Error('Connection error');
    
    // Simulate the race condition
    mockWsInstance.emit('error', error);

    // The promise should reject with the first error.
    await expect(createPromise).rejects.toThrow('Connection error');
    
    mockWsInstance.emit('close');
    expect(mockWsInstance.terminate).toHaveBeenCalledTimes(1);
  });

  it('should run a process, wait for output, and run another process', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockWsInstance.emit('open');
    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));
    const sandbox = await createPromise;

    // Run first process
    const process1Promise = sandbox.exec('bash', 'echo "hello"');
    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_EXECUTION_RUNNING,
    }));
    const process1 = await process1Promise;

    const stdoutPromise1 = new Promise<string>(resolve => {
      process1.stdout.on('data', (data) => resolve(data.toString()));
    });

    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STDOUT,
      [MessageKey.DATA]: 'hello\n',
    }));
    
    expect(await stdoutPromise1).toBe('hello\n');

    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_EXECUTION_DONE,
    }));
    await process1.wait();

    // Run second process
    const process2Promise = sandbox.exec('bash', 'echo "world"');
    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_EXECUTION_RUNNING,
    }));
    const process2 = await process2Promise;

    const stdoutPromise2 = new Promise<string>(resolve => {
      process2.stdout.on('data', (data) => resolve(data.toString()));
    });

    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STDOUT,
      [MessageKey.DATA]: 'world\n',
    }));

    expect(await stdoutPromise2).toBe('world\n');
  });

  it('should unblock stream consumers when the sandbox is terminated', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockWsInstance.emit('open');
    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));
    const sandbox = await createPromise;

    const processPromise = sandbox.exec('bash', 'sleep 10');
    mockWsInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_EXECUTION_RUNNING,
    }));
    const process = await processPromise;

    const stdoutPromise = process.stdout.readAll();
    const stderrPromise = process.stderr.readAll();

    sandbox.terminate();
    mockWsInstance.emit('close');

    // The streams should end, and the promises should resolve with empty strings.
    await expect(stdoutPromise).resolves.toBe('');
    await expect(stderrPromise).resolves.toBe('');
  });
  it('should successfully attach to a checkpointed sandbox and execute code', async () => {
    const attachPromise = Sandbox.attach('ws://test-url', 'test-id');

    // Simulate server responses for restoring
    mockWsInstance.emit('open');
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RESTORING' }));
    mockWsInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));

    const sandbox = await attachPromise;
    expect(sandbox).toBeInstanceOf(Sandbox);
    expect(sandbox.sandboxId).toBe('test-id');

    // Verify that exec works after attaching
    const execPromise = sandbox.exec('bash', 'echo "hello"');
    mockWsInstance.emit('message', JSON.stringify({
      "event": "status_update",
      "status": "SANDBOX_EXECUTION_RUNNING"
    }));
    await expect(execPromise).resolves.toBeInstanceOf(Object); // SandboxProcess
  });

  it('should handle a fatal checkpoint error', async () => {
    const createPromise = Sandbox.create('ws://test-url', { enableSandboxCheckpoint: true });
    mockWsInstance.emit('open');
    mockWsInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));
    const sandbox = await createPromise;

    const checkpointPromise = sandbox.checkpoint();

    // Simulate server responses for a failed checkpoint
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_CHECKPOINTING' }));
    mockWsInstance.emit('message', JSON.stringify({
      event: 'status_update',
      status: 'SANDBOX_CHECKPOINT_ERROR',
      message: 'Fatal checkpoint failure',
    }));

    await expect(checkpointPromise).rejects.toThrow('Fatal checkpoint failure');

    // Verify that exec fails after a fatal checkpoint error
    await expect(sandbox.exec('bash', 'echo "hello"')).rejects.toThrow('Sandbox is not in a running state. Current state: failed');
  });

  it('should handle a recoverable checkpoint error', async () => {
    const createPromise = Sandbox.create('ws://test-url', { enableSandboxCheckpoint: true });
    mockWsInstance.emit('open');
    mockWsInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));
    const sandbox = await createPromise;

    const checkpointPromise = sandbox.checkpoint();

    // Simulate server responses for a recoverable error
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_CHECKPOINTING' }));
    mockWsInstance.emit('message', JSON.stringify({
      event: 'status_update',
      status: 'SANDBOX_EXECUTION_IN_PROGRESS_ERROR',
      message: 'Execution in progress',
    }));

    await expect(checkpointPromise).rejects.toThrow('Execution in progress');

    // Verify that the sandbox state has returned to running
    expect((sandbox as any).state).toBe('running');
  });
  it('should correctly set the sandboxId when attaching', async () => {
    const testId = 'my-attach-test-id';
    const attachPromise = Sandbox.attach('ws://test-url', testId);

    // Simulate the server connection and successful restoration
    mockWsInstance.emit('open');
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RESTORING' }));
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));

    const sandbox = await attachPromise;
    
    // Assert that the sandboxId was set correctly on the client-side object
    expect(sandbox.sandboxId).toBe(testId);
  });

  it('should successfully create a filesystem snapshot', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockWsInstance.emit('open');
    mockWsInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));
    const sandbox = await createPromise;

    const snapshotPromise = sandbox.snapshotFilesystem('my-snapshot');

    // Simulate server responses
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_FILESYSTEM_SNAPSHOT_CREATING' }));
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_FILESYSTEM_SNAPSHOT_CREATED' }));

    await expect(snapshotPromise).resolves.toBeUndefined();
  });

  it('should handle a filesystem snapshot error', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockWsInstance.emit('open');
    mockWsInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));
    const sandbox = await createPromise;

    const snapshotPromise = sandbox.snapshotFilesystem('my-snapshot');

    // Simulate server responses for a failed snapshot
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_FILESYSTEM_SNAPSHOT_CREATING' }));
    mockWsInstance.emit('message', JSON.stringify({
      event: 'status_update',
      status: 'SANDBOX_FILESYSTEM_SNAPSHOT_ERROR',
      message: 'Snapshot failed',
    }));

    await expect(snapshotPromise).rejects.toThrow('Snapshot failed');
  });

  it('should reject snapshot if another snapshot is in progress', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockWsInstance.emit('open');
    mockWsInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));
    const sandbox = await createPromise;

    const snapshotPromise1 = sandbox.snapshotFilesystem('my-snapshot-1');
    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_FILESYSTEM_SNAPSHOT_CREATING' }));

    await expect(sandbox.snapshotFilesystem('my-snapshot-2')).rejects.toThrow('Sandbox is not in a running state. Current state: filesystem_snapshotting');

    mockWsInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_FILESYSTEM_SNAPSHOT_CREATED' }));
    await expect(snapshotPromise1).resolves.toBeUndefined();
  });
});
