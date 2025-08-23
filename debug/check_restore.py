import subprocess
import os
import json
import tempfile
import shutil
import sys
import time

def run_sync_command(cmd, check=True):
    """Helper to run a synchronous command and print its output."""
    print(f"--- Executing: {' '.join(cmd)} ---")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print("--- STDOUT ---")
        print(result.stdout)
    if result.stderr:
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
    config = {
        "ociVersion": "1.0.0",
        "process": {
            "user": {"uid": 0, "gid": 0},
            "args": command,
            "env": ["PATH=/usr/local/bin:/usr/bin:/bin"],
            "cwd": "/"
        },
        "root": {"path": "/", "readonly": True},
        "mounts": [{"destination": "/proc", "type": "proc", "source": "proc"}]
    }
    config_path = os.path.join(bundle_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
    print(f"--- Wrote config.json to {config_path} ---")
    return bundle_dir

def main():
    """
    Tests if a container started with 'runsc run' can be checkpointed and restored.
    """
    runsc_base_cmd = ["sudo", "runsc", "--platform=ptrace", "--network=none"]
    
    bundle_dir = tempfile.mkdtemp(prefix="runsc_checkpoint_")
    image_path = tempfile.mkdtemp(prefix="runsc_image_")
    container_id = "checkpoint-test"
    restored_container_id = "checkpoint-test-restored"
    
    run_proc = None
    restore_proc = None

    try:
        # A script that prints a number every second.
        counter_script = ["sh", "-c", "i=0; while true; do echo $i; i=$((i+1)); sleep 1; done"]
        create_bundle(bundle_dir, counter_script)

        # 1. Start the container in the background.
        run_cmd = runsc_base_cmd + ["run", "--bundle", bundle_dir, container_id]
        print(f"--- Starting container with command: {' '.join(run_cmd)} ---")
        run_proc = subprocess.Popen(run_cmd, stdout=subprocess.PIPE, text=True)

        # 2. Read the first few lines of output to see where we are.
        print("\n--- Reading initial output... ---")
        last_number = -1
        for i in range(4): # Read for 4 seconds
            line = run_proc.stdout.readline().strip()
            print(f"Read: {line}")
            try:
                last_number = int(line)
            except (ValueError, TypeError):
                print(f"Warning: Could not parse '{line}' as an integer.")
                continue
        
        if last_number < 2:
             print("--- Test failed: Did not receive enough initial output. ---")
             sys.exit(1)

        # 3. Checkpoint the container. This will stop it.
        print(f"\n--- Checkpointing container '{container_id}' (last number was {last_number}) ---")
        checkpoint_cmd = runsc_base_cmd + ["checkpoint", f"--image-path={image_path}", container_id]
        run_sync_command(checkpoint_cmd)
        
        # Wait for the original process to terminate.
        run_proc.wait(timeout=5)

        # 4. Restore the container.
        print(f"\n--- Restoring container to '{restored_container_id}' ---")
        restore_cmd = runsc_base_cmd + ["restore", "--bundle", bundle_dir, f"--image-path={image_path}", restored_container_id]
        restore_proc = subprocess.Popen(restore_cmd, stdout=subprocess.PIPE, text=True)

        # 5. Verify the first line of output from the restored container.
        print("\n--- Reading restored output... ---")
        restored_line = restore_proc.stdout.readline().strip()
        print(f"Read from restored: {restored_line}")
        restored_number = int(restored_line)

        print(f"\n--- Verification ---")
        print(f"Last number before checkpoint: {last_number}")
        print(f"First number after restore:    {restored_number}")

        assert restored_number == last_number + 1
        print("--- SUCCESS: Container resumed from the correct state! ---")

    finally:
        print("\n--- Cleaning up... ---")
        if run_proc:
            run_proc.kill()
        if restore_proc:
            restore_proc.kill()
        
        run_sync_command(runsc_base_cmd + ["delete", "--force", container_id], check=False)
        run_sync_command(runsc_base_cmd + ["delete", "--force", restored_container_id], check=False)
        
        if os.path.exists(bundle_dir):
            shutil.rmtree(bundle_dir)
        if os.path.exists(image_path):
            shutil.rmtree(image_path)

if __name__ == "__main__":
    main()
