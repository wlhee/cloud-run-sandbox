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

import subprocess
import os
import json
import tempfile
import shutil
import sys
import time

def run_command(cmd, check=True, capture_output=True):
    """
    Helper to run a command.
    Set capture_output=False to avoid deadlocks with commands that
    don't close their stdout/stderr, like 'runsc create'.
    """
    print(f"--- Executing: {' '.join(cmd)} ---")
    if capture_output:
        result = subprocess.run(cmd, capture_output=True, text=True)
        print("--- STDOUT ---")
        print(result.stdout)
        print("--- STDERR ---")
        print(result.stderr)
    else:
        # When not capturing, stdout/stderr go to the parent's streams
        result = subprocess.run(cmd)
    
    print(f"--- Exit Code: {result.returncode} ---")
    if check and result.returncode != 0:
        print("--- Command failed. Exiting. ---")
        sys.exit(1)
    return result

def create_bundle(bundle_dir, command):
    """Creates a minimal OCI bundle in the given directory."""
    print(f"\n--- Creating bundle in {bundle_dir} ---")
    
    config = {
        "ociVersion": "1.0.0",
        "process": {
            "user": {"uid": 0, "gid": 0},
            "args": command,
            "env": ["PATH=/usr/local/bin:/usr/bin:/bin"],
            "cwd": "/"
        },
        "root": {"path": "/", "readonly": True},
        "mounts": [
            {"destination": "/proc", "type": "proc", "source": "proc"}
        ]
    }
    config_path = os.path.join(bundle_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
    print(f"--- Wrote config.json to {config_path} ---")
    print(json.dumps(config, indent=4))
    return bundle_dir

def main():
    """
    Runs a gVisor lifecycle test to validate the fix for the 'runsc create' deadlock.
    """
    runsc_flags = [
        "sudo", "runsc",
        "--platform=ptrace",
        "--network=none",
        "--ignore-cgroups",
        "--debug",
        f"--debug-log=/tmp/runsc-debug/runsc_{int(time.time())}.log",
    ]

    print("\n\n--- Test: Full lifecycle: create, start, wait, delete ---")
    bundle_dir_lifecycle = tempfile.mkdtemp(prefix="runsc_lifecycle_")
    container_id = "lifecycle-test-container"
    try:
        create_bundle(bundle_dir_lifecycle, ["sh", "-c", "sleep 2 && echo '--- Hello from runsc lifecycle ---'"])
        
        print("\n--- Running CREATE ---")
        # We run 'create' with capture_output=False.
        # Using capture_output=True here would cause a deadlock because 'runsc create'
        # does not close the stdout/stderr file descriptors it passes to the sandbox.
        # Python's subprocess.run would wait indefinitely for those descriptors to close.
        run_command(runsc_flags + ["create", "--bundle", bundle_dir_lifecycle, container_id], capture_output=False)
        
        print("\n--- Running START ---")
        # 'start' is a short-lived command, so capturing its output is safe.
        run_command(runsc_flags + ["start", container_id])

        print("\n--- Running WAIT ---")
        # 'wait' will block until the container process exits. Capturing is safe.
        run_command(runsc_flags + ["wait", container_id])

    finally:
        print("\n--- Running DELETE (cleanup) ---")
        run_command(runsc_flags + ["delete", "--force", container_id], check=False)
        print(f"--- Cleaning up {bundle_dir_lifecycle} ---")
        shutil.rmtree(bundle_dir_lifecycle)

    print("\n\n--- Lifecycle debug test completed successfully! ---")

if __name__ == "__main__":
    main()
