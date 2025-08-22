import subprocess
import sys

def run_command(cmd, check=True):
    """Helper to run a command and print its output."""
    print(f"--- Executing: {' '.join(cmd)} ---")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"--- STDOUT ---\n{result.stdout}")
    print(f"--- STDERR ---\n{result.stderr}")
    print(f"--- Exit Code: {result.returncode} ---")
    if check and result.returncode != 0:
        print("--- Command failed. Exiting. ---")
        sys.exit(1)
    return result

def main():
    """
    Runs the simplest possible gVisor test.
    """
    runsc_flags = [
        "sudo", "runsc",
        "--platform=ptrace",
        "--network=none",
        "--ignore-cgroups"
    ]

    print("\n\n--- Test 1: Simple 'runsc do' ---")
    run_command(runsc_flags + ["do", "echo", "--- Hello from runsc do ---"])
    
    print("\n\n--- Minimal debug test completed successfully! ---")

if __name__ == "__main__":
    main()

