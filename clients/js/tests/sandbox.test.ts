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
    expect(mockWsInstance.send).toHaveBeenCalledWith(JSON.stringify({ idle_timeout: 60 }));

    sandbox.terminate();
    expect(mockWsInstance.close).toHaveBeenCalled();
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

    await expect(createPromise).rejects.toThrow('Connection closed during creation');
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
    const process1Promise = sandbox.exec('echo "hello"', 'bash');
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
    const process2Promise = sandbox.exec('echo "world"', 'bash');
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

    const processPromise = sandbox.exec('sleep 10', 'bash');
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
});
