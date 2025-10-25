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
import { Connection } from '../src/connection';
import { EventEmitter } from 'events';
import { jest } from '@jest/globals';
import { MessageKey, EventType, SandboxEvent } from '../src/types';

// Mock the Connection class
jest.mock('../src/connection');

const MockConnection = Connection as jest.MockedClass<typeof Connection>;

describe('Sandbox', () => {
  let mockConnectionInstance: EventEmitter & { send: jest.Mock; close: jest.Mock; };

  beforeEach(() => {
    // Create a fresh mock instance for each test
    mockConnectionInstance = new EventEmitter() as any;
    mockConnectionInstance.send = jest.fn();
    mockConnectionInstance.close = jest.fn();

    // Make the constructor return our mock instance
    MockConnection.mockImplementation(() => mockConnectionInstance as any);
    MockConnection.mockClear();
  });

  it('should create and kill a sandbox successfully', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    
    mockConnectionInstance.emit('open');

    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));

    const sandbox = await createPromise;

    expect(sandbox).toBeInstanceOf(Sandbox);
    expect(sandbox.sandboxId).toBe('test-id');
    expect(mockConnectionInstance.send).toHaveBeenCalledWith(JSON.stringify({
      idle_timeout: 60,
      enable_checkpoint: false,
      enable_sandbox_handoff: false,
      filesystem_snapshot_name: undefined,
    }));

    const killPromise = sandbox.kill();
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_KILLED,
    }));
    await killPromise;
    expect(mockConnectionInstance.close).toHaveBeenCalled();
  });

  it('should create a sandbox with checkpointing enabled', async () => {
    const createPromise = Sandbox.create('ws://test-url', { enableSandboxCheckpoint: true });
    
    mockConnectionInstance.emit('open');

    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));

    const sandbox = await createPromise;

    expect(sandbox).toBeInstanceOf(Sandbox);
    expect(sandbox.sandboxId).toBe('test-id');
    expect(mockConnectionInstance.send).toHaveBeenCalledWith(JSON.stringify({
      idle_timeout: 60,
      enable_checkpoint: true,
      enable_sandbox_handoff: false,
      filesystem_snapshot_name: undefined,
    }));

    const killPromise = sandbox.kill();
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_KILLED,
    }));
    await killPromise;
    expect(mockConnectionInstance.close).toHaveBeenCalled();
  });

  it('should create a sandbox with handoff enabled', async () => {
    const createPromise = Sandbox.create('ws://test-url', { enableSandboxHandoff: true });
    
    mockConnectionInstance.emit('open');

    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));

    const sandbox = await createPromise;

    expect(sandbox).toBeInstanceOf(Sandbox);
    expect(sandbox.sandboxId).toBe('test-id');
    expect(mockConnectionInstance.send).toHaveBeenCalledWith(JSON.stringify({
      idle_timeout: 60,
      enable_checkpoint: false,
      enable_sandbox_handoff: true,
      filesystem_snapshot_name: undefined,
    }));

    const killPromise = sandbox.kill();
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_KILLED,
    }));
    await killPromise;
    expect(mockConnectionInstance.close).toHaveBeenCalled();
  });

  it('should log debug messages with label when enabled', async () => {
    const consoleLogSpy = jest.spyOn(console, 'log').mockImplementation(() => {});
    const createPromise = Sandbox.create('ws://test-url', { enableDebug: true, debugLabel: 'TestSandbox' });
    
    mockConnectionInstance.emit('open');

    const sandboxIdMessage = {
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    };
    mockConnectionInstance.emit('message', JSON.stringify(sandboxIdMessage));
    
    const runningMessage = {
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    };
    mockConnectionInstance.emit('message', JSON.stringify(runningMessage));

    await createPromise;

    expect(consoleLogSpy).toHaveBeenCalledWith('[TestSandbox] [DEBUG] Received message:', sandboxIdMessage);
    expect(consoleLogSpy).toHaveBeenCalledWith('[TestSandbox] [DEBUG] Received message:', runningMessage);

    consoleLogSpy.mockRestore();
  });

  it('should create a sandbox with a filesystem snapshot', async () => {
    const createPromise = Sandbox.create('ws://test-url', { filesystemSnapshotName: 'my-snapshot' });
    
    mockConnectionInstance.emit('open');

    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));

    const sandbox = await createPromise;

    expect(sandbox).toBeInstanceOf(Sandbox);
    expect(sandbox.sandboxId).toBe('test-id');
    expect(mockConnectionInstance.send).toHaveBeenCalledWith(JSON.stringify({
      idle_timeout: 60,
      enable_checkpoint: false,
      enable_sandbox_handoff: false,
      filesystem_snapshot_name: 'my-snapshot',
    }));

    const killPromise = sandbox.kill();
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_KILLED,
    }));
    await killPromise;
    expect(mockConnectionInstance.close).toHaveBeenCalled();
  });

  it('should successfully checkpoint a sandbox and prevent further execution', async () => {
    const createPromise = Sandbox.create('ws://test-url', { enableSandboxCheckpoint: true });
    mockConnectionInstance.emit('open');
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));
    const sandbox = await createPromise;

    const checkpointPromise = sandbox.checkpoint();

    // Simulate server responses
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_CHECKPOINTING' }));
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_CHECKPOINTED' }));

    await expect(checkpointPromise).resolves.toBeUndefined();

    // Verify that exec fails after checkpointing
    await expect(sandbox.exec('bash', 'echo "hello"')).rejects.toThrow('Sandbox is not in a running state. Current state: checkpointed');
  });

  it('should reject creation on server error and terminate the socket', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockConnectionInstance.emit('open');

    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_CREATION_ERROR,
      [MessageKey.MESSAGE]: 'Creation failed',
    }));

    await expect(createPromise).rejects.toThrow('Creation failed');
    expect(mockConnectionInstance.close).toHaveBeenCalled();
  });

  it('should reject creation on connection error and terminate the socket', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    const error = new Error('Connection error');
    mockConnectionInstance.emit('error', error);

    await expect(createPromise).rejects.toThrow('Connection error');
    expect(mockConnectionInstance.close).toHaveBeenCalled();
  });

  it('should reject creation if connection closes prematurely and terminate the socket', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockConnectionInstance.emit('open');
    mockConnectionInstance.emit('close');

    await expect(createPromise).rejects.toThrow('Connection closed during creation/restoration: code=undefined');
    expect(mockConnectionInstance.close).toHaveBeenCalled();
  });

  it('should reject only once and terminate if error and close are both emitted', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    const error = new Error('Connection error');
    
    // Simulate the race condition
    mockConnectionInstance.emit('error', error);

    // The promise should reject with the first error.
    await expect(createPromise).rejects.toThrow('Connection error');
    
    mockConnectionInstance.emit('close');
    expect(mockConnectionInstance.close).toHaveBeenCalledTimes(1);
  });

  it('should run a process, wait for output, and run another process', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockConnectionInstance.emit('open');
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));
    const sandbox = await createPromise;

    // Run first process
    const process1Promise = sandbox.exec('bash', 'echo "hello"');
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_EXECUTION_RUNNING,
    }));
    const process1 = await process1Promise;

    const stdoutPromise1 = new Promise<string>(resolve => {
      process1.stdout.on('data', (data) => resolve(data.toString()));
    });

    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STDOUT,
      [MessageKey.DATA]: 'hello\n',
    }));
    
    expect(await stdoutPromise1).toBe('hello\n');

    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_EXECUTION_DONE,
    }));
    await process1.wait();

    // Run second process
    const process2Promise = sandbox.exec('bash', 'echo "world"');
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_EXECUTION_RUNNING,
    }));
    const process2 = await process2Promise;

    const stdoutPromise2 = new Promise<string>(resolve => {
      process2.stdout.on('data', (data) => resolve(data.toString()));
    });

    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STDOUT,
      [MessageKey.DATA]: 'world\n',
    }));

    expect(await stdoutPromise2).toBe('world\n');
  });

  it('should unblock stream consumers when the sandbox is killed', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockConnectionInstance.emit('open');
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));
    const sandbox = await createPromise;

    const processPromise = sandbox.exec('bash', 'sleep 10');
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_EXECUTION_RUNNING,
    }));
    const process = await processPromise;

    const stdoutPromise = process.stdout.readAll();
    const stderrPromise = process.stderr.readAll();

    const killPromise = sandbox.kill();
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_KILLED,
    }));
    await killPromise;
    mockConnectionInstance.emit('close');

    // The streams should end, and the promises should resolve with empty strings.
    await expect(stdoutPromise).resolves.toBe('');
    await expect(stderrPromise).resolves.toBe('');
  });
  it('should successfully attach to a checkpointed sandbox and execute code', async () => {
    const attachPromise = Sandbox.attach('ws://test-url', 'test-id');

    // Simulate server responses for restoring
    mockConnectionInstance.emit('open');
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RESTORING' }));
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));

    const sandbox = await attachPromise;
    expect(sandbox).toBeInstanceOf(Sandbox);
    expect(sandbox.sandboxId).toBe('test-id');

    // Verify that exec works after attaching
    const execPromise = sandbox.exec('bash', 'echo "hello"');
    mockConnectionInstance.emit('message', JSON.stringify({
      "event": "status_update",
      "status": "SANDBOX_EXECUTION_RUNNING"
    }));
    await expect(execPromise).resolves.toBeInstanceOf(Object); // SandboxProcess
  });

  it('should handle a fatal checkpoint error', async () => {
    const createPromise = Sandbox.create('ws://test-url', { enableSandboxCheckpoint: true });
    mockConnectionInstance.emit('open');
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));
    const sandbox = await createPromise;

    const checkpointPromise = sandbox.checkpoint();

    // Simulate server responses for a failed checkpoint
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_CHECKPOINTING' }));
    mockConnectionInstance.emit('message', JSON.stringify({
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
    mockConnectionInstance.emit('open');
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));
    const sandbox = await createPromise;

    const checkpointPromise = sandbox.checkpoint();

    // Simulate server responses for a recoverable error
    mockConnectionInstance.emit('message', JSON.stringify({
      event: 'status_update',
      status: 'SANDBOX_CHECKPOINTING'
    }));
    mockConnectionInstance.emit('message', JSON.stringify({
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
    mockConnectionInstance.emit('open');
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RESTORING' }));
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));

    const sandbox = await attachPromise;
    
    // Assert that the sandboxId was set correctly on the client-side object
    expect(sandbox.sandboxId).toBe(testId);
  });

  it('should successfully create a filesystem snapshot', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockConnectionInstance.emit('open');
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));
    const sandbox = await createPromise;

    const snapshotPromise = sandbox.snapshotFilesystem('my-snapshot');

    // Simulate server responses
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_FILESYSTEM_SNAPSHOT_CREATING' }));
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_FILESYSTEM_SNAPSHOT_CREATED' }));

    await expect(snapshotPromise).resolves.toBeUndefined();
  });

  it('should handle a filesystem snapshot error', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockConnectionInstance.emit('open');
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));
    const sandbox = await createPromise;

    const snapshotPromise = sandbox.snapshotFilesystem('my-snapshot');

    // Simulate server responses for a failed snapshot
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_FILESYSTEM_SNAPSHOT_CREATING' }));
    mockConnectionInstance.emit('message', JSON.stringify({
      event: 'status_update',
      status: 'SANDBOX_FILESYSTEM_SNAPSHOT_ERROR',
      message: 'Snapshot failed',
    }));

    await expect(snapshotPromise).rejects.toThrow('Snapshot failed');
  });

  it('should reject snapshot if another snapshot is in progress', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockConnectionInstance.emit('open');
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'sandbox_id', sandbox_id: 'test-id' }));
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_RUNNING' }));
    const sandbox = await createPromise;

    const snapshotPromise1 = sandbox.snapshotFilesystem('my-snapshot-1');
    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_FILESYSTEM_SNAPSHOT_CREATING' }));

    await expect(sandbox.snapshotFilesystem('my-snapshot-2')).rejects.toThrow('Sandbox is not in a running state. Current state: filesystem_snapshotting');

    mockConnectionInstance.emit('message', JSON.stringify({ event: 'status_update', status: 'SANDBOX_FILESYSTEM_SNAPSHOT_CREATED' }));
    await expect(snapshotPromise1).resolves.toBeUndefined();
  });

  describe('reconnection', () => {
    it('should enable reconnection after sandbox is running', async () => {
      const createPromise = Sandbox.create('ws://test-url', { enableAutoReconnect: true });
      mockConnectionInstance.emit('open');
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.SANDBOX_ID,
        [MessageKey.SANDBOX_ID]: 'test-id',
      }));
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
      }));

      const sandbox = await createPromise;

      // After running, should be true
      expect((sandbox as any)._shouldReconnect).toBe(true);
    });

    it('should change state to reconnecting on connection close', async () => {
      const createPromise = Sandbox.create('ws://test-url', { enableAutoReconnect: true });
      mockConnectionInstance.emit('open');
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.SANDBOX_ID,
        [MessageKey.SANDBOX_ID]: 'test-id',
      }));
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
      }));
      const sandbox = await createPromise;

      const decision = sandbox.shouldReconnect(1006, Buffer.from('Abnormal closure'));

      expect(decision).toBe(true);
      expect((sandbox as any).state).toBe('reconnecting');
    });

    it('should provide correct reconnect info', async () => {
      const createPromise = Sandbox.create('ws://test-url', { wsOptions: { headers: { 'X-Test': 'true' } }, enableAutoReconnect: true });
      mockConnectionInstance.emit('open');
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.SANDBOX_ID,
        [MessageKey.SANDBOX_ID]: 'test-id-reconnect',
      }));
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
      }));
      const sandbox = await createPromise;

      const getReconnectInfo = MockConnection.mock.calls[0][2];
      const info = getReconnectInfo();

      expect(info.url).toBe('ws://test-url/attach/test-id-reconnect');
      expect(info.wsOptions).toEqual({ headers: { 'X-Test': 'true' } });
    });

    it('should buffer and flush stdin during reconnection', async () => {
      const createPromise = Sandbox.create('ws://test-url', { enableAutoReconnect: true });
      mockConnectionInstance.emit('open');
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.SANDBOX_ID,
        [MessageKey.SANDBOX_ID]: 'test-id',
      }));
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
      }));
      const sandbox = await createPromise;

      const processPromise = sandbox.exec('python', 'input()');
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_EXECUTION_RUNNING,
      }));
      const process = await processPromise;

      // Trigger reconnection
      sandbox.shouldReconnect(1006, Buffer.from('Abnormal closure'));
      expect((sandbox as any).state).toBe('reconnecting');

      // Send stdin while reconnecting
      process.writeToStdin('buffered message');

      // Should not be sent immediately
      expect(mockConnectionInstance.send).not.toHaveBeenCalledWith(expect.stringContaining('buffered message'));

      // Simulate successful reconnection
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
      }));

      // Should be sent after reconnection
      expect(mockConnectionInstance.send).toHaveBeenCalledWith(JSON.stringify({
        event: 'stdin',
        data: 'buffered message',
      }));
    });
    it('should not reconnect after intentional checkpoint', async () => {
      const createPromise = Sandbox.create('ws://test-url', { enableAutoReconnect: true });
      mockConnectionInstance.emit('open');
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.SANDBOX_ID,
        [MessageKey.SANDBOX_ID]: 'test-id',
      }));
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
      }));
      const sandbox = await createPromise;

      // Intentionally checkpoint
      const checkpointPromise = sandbox.checkpoint();
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_CHECKPOINTED,
      }));
      await checkpointPromise;

      const decision = sandbox.shouldReconnect(1000, Buffer.from('Normal closure'));
      expect(decision).toBe(false);
    });

    it.each([
      [SandboxEvent.SANDBOX_ERROR],
      [SandboxEvent.SANDBOX_NOT_FOUND],
      [SandboxEvent.SANDBOX_CREATION_ERROR],
      [SandboxEvent.SANDBOX_CHECKPOINT_ERROR],
      [SandboxEvent.SANDBOX_RESTORE_ERROR],
      [SandboxEvent.SANDBOX_DELETED],
      [SandboxEvent.SANDBOX_LOCK_RENEWAL_ERROR],
    ])('should not reconnect after a fatal error: %s', async (errorStatus) => {
      const createPromise = Sandbox.create('ws://test-url', { enableAutoReconnect: true });
      mockConnectionInstance.emit('open');
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
      }));
      const sandbox = await createPromise;

      // Ensure reconnect is initially true
      expect((sandbox as any)._shouldReconnect).toBe(true);

      // Simulate a fatal error
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: errorStatus,
      }));

      // The decision should now be false
      const decision = sandbox.shouldReconnect(1006, Buffer.from('Abnormal closure'));
      expect(decision).toBe(false);
    });
  });
  
  it('should kill the active process on force-kill event', async () => {
    const createPromise = Sandbox.create('ws://test-url');
    mockConnectionInstance.emit('open');
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.SANDBOX_ID,
      [MessageKey.SANDBOX_ID]: 'test-id',
    }));
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
    }));
    const sandbox = await createPromise;

    // Start a process
    const processPromise = sandbox.exec('bash', 'sleep 10');
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_EXECUTION_RUNNING,
    }));
    const process = await processPromise;
    
    // Verify process is active
    expect((sandbox as any).activeProcess).not.toBeNull();

    const waitPromise = process.wait();

    // Simulate the force-kill event
    mockConnectionInstance.emit('message', JSON.stringify({
      [MessageKey.EVENT]: EventType.STATUS_UPDATE,
      [MessageKey.STATUS]: SandboxEvent.SANDBOX_EXECUTION_FORCE_KILLED,
    }));

    // Assert that the process is now done
    await expect(waitPromise).resolves.toBeUndefined();
    
    // Assert that the sandbox has no active process
    expect((sandbox as any).activeProcess).toBeNull();
  });

  describe('kill', () => {
    beforeEach(() => {
      jest.useFakeTimers();
    });

    afterEach(() => {
      jest.useRealTimers();
    });

    it('should send a kill_sandbox action and resolve on SANDBOX_KILLED', async () => {
      const createPromise = Sandbox.create('ws://test-url');
      mockConnectionInstance.emit('open');
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
      }));
      const sandbox = await createPromise;

      const killPromise = sandbox.kill();

      expect(mockConnectionInstance.send).toHaveBeenCalledWith(JSON.stringify({
        action: 'kill_sandbox',
      }));

      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_KILLED,
      }));

      await expect(killPromise).resolves.toBeUndefined();
      expect(mockConnectionInstance.close).toHaveBeenCalled();
    });

    it('should resolve on SANDBOX_KILL_ERROR', async () => {
      const createPromise = Sandbox.create('ws://test-url');
      mockConnectionInstance.emit('open');
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
      }));
      const sandbox = await createPromise;

      const killPromise = sandbox.kill();

      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_KILL_ERROR,
      }));

      await expect(killPromise).resolves.toBeUndefined();
      expect(mockConnectionInstance.close).toHaveBeenCalled();
    });

    it('should time out and close the connection if no event is received', async () => {
      const createPromise = Sandbox.create('ws://test-url');
      mockConnectionInstance.emit('open');
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
      }));
      const sandbox = await createPromise;

      const killPromise = sandbox.kill();

      jest.advanceTimersByTime(5000);

      await expect(killPromise).resolves.toBeUndefined();
      expect(mockConnectionInstance.close).toHaveBeenCalled();
    });

    it.each(['closed', 'failed', 'checkpointed'])
    ('should resolve immediately if the sandbox state is %s', async (state) => {
      const createPromise = Sandbox.create('ws://test-url');
      mockConnectionInstance.emit('open');
      mockConnectionInstance.emit('message', JSON.stringify({
        [MessageKey.EVENT]: EventType.STATUS_UPDATE,
        [MessageKey.STATUS]: SandboxEvent.SANDBOX_RUNNING,
      }));
      const sandbox = await createPromise;
      (sandbox as any).state = state;

      // Clear the mock so we can check that send is not called by kill()
      mockConnectionInstance.send.mockClear();

      const killPromise = sandbox.kill();

      await expect(killPromise).resolves.toBeUndefined();
      expect(mockConnectionInstance.send).not.toHaveBeenCalled();
      expect(mockConnectionInstance.close).not.toHaveBeenCalled();
    });
  });
});
