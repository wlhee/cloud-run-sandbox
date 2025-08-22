import subprocess
import os
import json
import tempfile
import shutil
import sys

def run_command(cmd, check=True):
    """Helper to run a command and print its output."""
    print(f"--- Executing: {' '.join(cmd)} ---")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print("--- STDOUT ---")
    print(result.stdout)
    print("--- STDERR ---")
    print(result.stderr)
    print(f"--- Exit Code: {result.returncode} ---")
    if check and result.returncode != 0:
        print("--- Command failed. Exiting. ---")
        sys.exit(1)
    return result

def create_bundle(bundle_dir, command):
    """Creates a minimal OCI bundle in the given directory."""
    print(f"\n--- Creating bundle in {bundle_dir} ---")
    
    # The config.json is minimal, using the host's rootfs
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
    Runs a series of increasingly complex gVisor tests to debug the CI environment.
    """
    # Common runsc flags
    runsc_flags = [
        "sudo", "runsc",
        #"--platform=ptrace",
        "--network=none",
        "--ignore-cgroups",
        "--debug",
        "--debug-log=/dev/stderr",        
    ]

    # --- Test 1: runsc do ---
    print("\n\n--- Test 1: Simple 'runsc do' ---")
    run_command(runsc_flags + ["do", "echo", "--- Hello from runsc do ---"])

    # --- Test 2: runsc run --bundle ---
    print("\n\n--- Test 2: Synchronous 'runsc run' with a bundle ---")
    bundle_dir_run = tempfile.mkdtemp(prefix="runsc_run_")
    try:
        create_bundle(bundle_dir_run, ["echo", "--- Hello from runsc run ---"])
        run_command(runsc_flags + ["run", "--bundle", bundle_dir_run, "run-test-container"])
    finally:
        print(f"--- Cleaning up {bundle_dir_run} ---")
        shutil.rmtree(bundle_dir_run)

    # --- Test 3: runsc create -> start -> wait -> delete ---
    print("\n\n--- Test 3: Full lifecycle: create, start, wait, delete ---")
    bundle_dir_lifecycle = tempfile.mkdtemp(prefix="runsc_lifecycle_")
    container_id = "lifecycle-test-container"
    try:
        create_bundle(bundle_dir_lifecycle, ["echo", "--- Hello from runsc lifecycle ---"])
        
        print("\n--- Running CREATE ---")
        run_command(runsc_flags + ["create", "--bundle", bundle_dir_lifecycle, container_id])
        
        print("\n--- Running START ---")
        # 'start' is asynchronous, so we don't check its exit code immediately
        run_command(runsc_flags + ["start", container_id], check=False)

        print("\n--- Running WAIT ---")
        run_command(runsc_flags + ["wait", container_id])

    finally:
        print("\n--- Running DELETE (cleanup) ---")
        run_command(runsc_flags + ["delete", "--force", container_id], check=False)
        print(f"--- Cleaning up {bundle_dir_lifecycle} ---")
        shutil.rmtree(bundle_dir_lifecycle)

    print("\n\n--- All debug tests completed successfully! ---")

if __name__ == "__main__":
    main()
