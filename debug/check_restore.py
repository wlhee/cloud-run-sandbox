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
    Tests if a container started with 'runsc run' can be checkpointed,
    restored, and can still execute new commands.
    """
    runsc_base_cmd = ["runsc", "--network=none"]
    
    bundle_dir = tempfile.mkdtemp(prefix="runsc_exec_")
    image_path = tempfile.mkdtemp(prefix="runsc_image_")
    container_id = "exec-test"
    restored_container_id = "exec-test-restored"
    
    run_proc = None

    try:
        # Start a long-running shell process
        create_bundle(bundle_dir, ["sh", "-c", "i=0; while true; do echo $i; i=$(expr $i + 1); sleep 1; done"])  

        # 1. Start the container in the background.
        run_cmd = runsc_base_cmd + ["run", "--bundle", bundle_dir, container_id]
        print(f"--- Starting container with command: {' '.join(run_cmd)} ---")
        run_proc = subprocess.Popen(run_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(2) # Give it a moment to stabilize

        # 2. Execute the first command.
        print("\n--- Executing first command before checkpoint ---")
        exec_cmd1 = runsc_base_cmd + ["exec", container_id, "which", "sh"]
        result1 = run_sync_command(exec_cmd1)
        assert "hello from first exec" in result1.stdout

        # 3. Checkpoint the container.
        print(f"\n--- Checkpointing container '{container_id}' ---")
        checkpoint_cmd = runsc_base_cmd + ["checkpoint", f"--image-path={image_path}", container_id]
        run_sync_command(checkpoint_cmd)
        run_proc.wait(timeout=5)

        # 4. Restore the container.
        print("\n--- Restoring container to '" + restored_container_id + "' ---")
        # Note: 'restore' also needs a process to run in the background
        restore_cmd = runsc_base_cmd + ["restore", "--bundle", bundle_dir, f"--image-path={image_path}", restored_container_id]
        restore_proc = subprocess.Popen(restore_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(2) # Give it a moment to stabilize

        # 5. Execute the second command on the restored container.
        print("\n--- Executing second command after restore ---")
        exec_cmd2 = runsc_base_cmd + ["exec", restored_container_id, "echo", "hello from second exec"]
        result2 = run_sync_command(exec_cmd2)
        assert "hello from second exec" in result2.stdout

        print("\n--- SUCCESS: Container checkpointed, restored, and exec still works! ---")

    finally:
        print("\n--- Cleaning up... ---")
        if run_proc:
            run_proc.kill()
        if 'restore_proc' in locals() and restore_proc:
            restore_proc.kill()
        
        run_sync_command(runsc_base_cmd + ["delete", "--force", container_id], check=False)
        run_sync_command(runsc_base_cmd + ["delete", "--force", restored_container_id], check=False)
        
        if os.path.exists(bundle_dir):
            shutil.rmtree(bundle_dir)
        if os.path.exists(image_path):
            shutil.rmtree(image_path)

if __name__ == "__main__":
    main()
