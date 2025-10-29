# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from enum import Enum

class MessageKey(str, Enum):
    """
    Top-level keys in the JSON messages from the server.
    """
    EVENT = "event"
    STATUS = "status"
    DATA = "data"
    SANDBOX_ID = "sandbox_id"
    MESSAGE = "message"

class EventType(str, Enum):
    """
    Values for the 'event' key in a server message.
    """
    STATUS_UPDATE = "status_update"
    SANDBOX_ID = "sandbox_id"
    STDOUT = "stdout"
    STDERR = "stderr"
    ERROR = "error"

class SandboxEvent(str, Enum):
    """
    Values for the 'status' key when the event is 'status_update'.
    """
    SANDBOX_CREATING = "SANDBOX_CREATING"
    SANDBOX_RUNNING = "SANDBOX_RUNNING"
    SANDBOX_NOT_FOUND = "SANDBOX_NOT_FOUND"
    SANDBOX_IN_USE = "SANDBOX_IN_USE"
    SANDBOX_CREATION_ERROR = "SANDBOX_CREATION_ERROR"
    
    SANDBOX_EXECUTION_RUNNING = "SANDBOX_EXECUTION_RUNNING"
    SANDBOX_EXECUTION_DONE = "SANDBOX_EXECUTION_DONE"
    SANDBOX_EXECUTION_ERROR = "SANDBOX_EXECUTION_ERROR"
