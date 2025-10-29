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
  SANDBOX_ERROR = 'SANDBOX_ERROR',
  SANDBOX_CREATING = 'SANDBOX_CREATING',
  SANDBOX_RUNNING = 'SANDBOX_RUNNING',
  SANDBOX_CREATION_ERROR = 'SANDBOX_CREATION_ERROR',
  SANDBOX_EXECUTION_RUNNING = 'SANDBOX_EXECUTION_RUNNING',
  SANDBOX_EXECUTION_DONE = 'SANDBOX_EXECUTION_DONE',
  SANDBOX_EXECUTION_ERROR = 'SANDBOX_EXECUTION_ERROR',
  SANDBOX_EXECUTION_UNSUPPORTED_LANGUAGE_ERROR = 'SANDBOX_EXECUTION_UNSUPPORTED_LANGUAGE_ERROR',
  SANDBOX_EXECUTION_FORCE_KILLED = 'SANDBOX_EXECUTION_FORCE_KILLED',
  SANDBOX_EXECUTION_FORCE_KILL_ERROR = 'SANDBOX_EXECUTION_FORCE_KILL_ERROR',
  SANDBOX_CHECKPOINTING = 'SANDBOX_CHECKPOINTING',
  SANDBOX_CHECKPOINTED = 'SANDBOX_CHECKPOINTED',
  SANDBOX_CHECKPOINT_ERROR = 'SANDBOX_CHECKPOINT_ERROR',
  SANDBOX_RESTORING = 'SANDBOX_RESTORING',
  SANDBOX_RESTORE_ERROR = 'SANDBOX_RESTORE_ERROR',
  SANDBOX_NOT_FOUND = 'SANDBOX_NOT_FOUND',
  SANDBOX_IN_USE = 'SANDBOX_IN_USE',
  SANDBOX_EXECUTION_IN_PROGRESS_ERROR = 'SANDBOX_EXECUTION_IN_PROGRESS_ERROR',
  SANDBOX_FILESYSTEM_SNAPSHOT_CREATING = 'SANDBOX_FILESYSTEM_SNAPSHOT_CREATING',
  SANDBOX_FILESYSTEM_SNAPSHOT_CREATED = 'SANDBOX_FILESYSTEM_SNAPSHOT_CREATED',
  SANDBOX_FILESYSTEM_SNAPSHOT_ERROR = 'SANDBOX_FILESYSTEM_SNAPSHOT_ERROR',
  SANDBOX_DELETED = 'SANDBOX_DELETED',
  SANDBOX_LOCK_RENEWAL_ERROR = 'SANDBOX_LOCK_RENEWAL_ERROR',
  SANDBOX_LOCK_RELEASING = 'SANDBOX_LOCK_RELEASING',
  SANDBOX_LOCK_RELEASED = 'SANDBOX_LOCK_RELEASED',
  SANDBOX_KILLING = 'SANDBOX_KILLING',
  SANDBOX_KILLED = 'SANDBOX_KILLED',
  SANDBOX_KILL_ERROR = 'SANDBOX_KILL_ERROR',
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
