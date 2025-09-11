export enum MessageKey {
  EVENT = 'event',
  STATUS = 'status',
  MESSAGE = 'message',
  SANDBOX_ID = 'sandbox_id',
  DATA = 'data',
}

export enum EventType {
  STATUS_UPDATE = 'status_update',
  SANDBOX_ID = 'sandbox_id',
  STDOUT = 'stdout',
  STDERR = 'stderr',
}

export enum SandboxEvent {
  SANDBOX_RUNNING = 'sandbox_running',
  SANDBOX_CREATION_ERROR = 'sandbox_creation_error',
  SANDBOX_EXECUTION_RUNNING = 'sandbox_execution_running',
  SANDBOX_EXECUTION_DONE = 'sandbox_execution_done',
  SANDBOX_EXECUTION_ERROR = 'sandbox_execution_error',
}

export interface BaseMessage {
  [MessageKey.EVENT]: EventType;
}

export interface StatusUpdateMessage extends BaseMessage {
  [MessageKey.EVENT]: EventType.STATUS_UPDATE;
  [MessageKey.STATUS]: SandboxEvent;
  [MessageKey.MESSAGE]?: string;
}

export interface SandboxIdMessage extends BaseMessage {
  [MessageKey.EVENT]: EventType.SANDBOX_ID;
  [MessageKey.SANDBOX_ID]: string;
}

export interface StdoutMessage extends BaseMessage {
  [MessageKey.EVENT]: EventType.STDOUT;
  [MessageKey.DATA]: string;
}

export interface StderrMessage extends BaseMessage {
  [MessageKey.EVENT]: EventType.STDERR;
  [MessageKey.DATA]: string;
}

export type WebSocketMessage =
  | StatusUpdateMessage
  | SandboxIdMessage
  | StdoutMessage
  | StderrMessage;
