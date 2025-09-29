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
  ERROR = 'error',
}

export enum SandboxEvent {
  SANDBOX_CREATING = 'SANDBOX_CREATING',
  SANDBOX_RUNNING = 'SANDBOX_RUNNING',
  SANDBOX_CREATION_ERROR = 'SANDBOX_CREATION_ERROR',
  SANDBOX_EXECUTION_RUNNING = 'SANDBOX_EXECUTION_RUNNING',
  SANDBOX_EXECUTION_DONE = 'SANDBOX_EXECUTION_DONE',
  SANDBOX_EXECUTION_ERROR = 'SANDBOX_EXECUTION_ERROR',
  SANDBOX_CHECKPOINTING = 'SANDBOX_CHECKPOINTING',
  SANDBOX_CHECKPOINTED = 'SANDBOX_CHECKPOINTED',
  SANDBOX_CHECKPOINT_ERROR = 'SANDBOX_CHECKPOINT_ERROR',
  SANDBOX_RESTORING = 'SANDBOX_RESTORING',
  SANDBOX_RESTORE_ERROR = 'SANDBOX_RESTORE_ERROR',
  SANDBOX_NOT_FOUND = 'SANDBOX_NOT_FOUND',
  SANDBOX_IN_USE = 'SANDBOX_IN_USE',
  SANDBOX_EXECUTION_IN_PROGRESS_ERROR = 'SANDBOX_EXECUTION_IN_PROGRESS_ERROR',
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
