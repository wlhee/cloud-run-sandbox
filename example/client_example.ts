/**
 * A simple example demonstrating how to use the Cloud Run Sandbox TypeScript client. 
 * 
 * This script expects the URL of your deployed Cloud Run service to be
 * set in the `CLOUD_RUN_URL` environment variable.
 * 
 * The WebSocket URL should be in the format: wss://<your-cloud-run-url>
 * 
 * To run this example:
 * 1. Make sure you have ts-node installed (`npm install -g ts-node`).
 * 2. Set the environment variable:
 *    `export CLOUD_RUN_URL="wss://your-service-url.run.app"
 * 3. Run the script from the root of the repository:
 *    `ts-node example/client_example.ts`
 */
import { Sandbox } from '../clients/js/src/sandbox';

async function main() {
  const url = process.env.CLOUD_RUN_URL;
  if (!url) {
    console.error("Error: Please set the CLOUD_RUN_URL environment variable.");
    console.error("Example: export CLOUD_RUN_URL=\"wss://your-service-url.run.app\"");
    return;
  }

  console.log(`Connecting to sandbox at ${url}...`);
  let sandbox: Sandbox | undefined;

  try {
    // Create a new sandbox session, with a 10-second timeout.
    const timeoutPromise = new Promise<Sandbox>((_, reject) => 
      setTimeout(() => reject(new Error('Connection timed out after 10 seconds')), 10000)
    );
    
    sandbox = await Promise.race([
      Sandbox.create(url),
      timeoutPromise
    ]);

    console.log(`Successfully created sandbox with ID: ${sandbox.sandboxId}`);

    // Execute a bash command
    console.log("\nExecuting command: echo 'Hello from bash!'");
    const process = await sandbox.exec("echo 'Hello from bash!'", "bash");

    // Concurrently read streams and wait for the process to complete
    const [stdout, stderr] = await Promise.all([
      process.stdout.readAll(),
      process.stderr.readAll(),
      process.wait(),
    ]);
    
    console.log("\n--- Bash Output ---");
    if (stdout) {
      console.log(`STDOUT:\n${stdout}`);
    }
    if (stderr) {
      console.log(`STDERR:\n${stderr}`);
    }
    console.log("-------------------");
    console.log('Process finished.');

    // Iterative read example
    console.log("\nExecuting Python script and reading output iteratively...");
    const pythonScript = `
import time
for i in range(5):
    print(f"Line {i+1}")
    time.sleep(0.5)
`;
    const pythonProcess = await sandbox.exec(pythonScript, "python");

    console.log("\n--- Python Output (Iterative) ---");
    for await (const chunk of pythonProcess.stdout) {
      console.log(chunk.toString());
    }
    console.log("---------------------------------");
    await pythonProcess.wait();
    console.log('Python script finished.');


    // Stdin example
    console.log("\nExecuting Python script and writing to stdin...");
    const stdinScript = `
import sys
print("Python script waiting for 2 lines from stdin...")
for i in range(2):
    line = sys.stdin.readline()
    print(f"Read from stdin: {line.strip()}")
print("Python script finished.")
`;
    const stdinProcess = await sandbox.exec(stdinScript, "python");

    // Write to stdin after a short delay
    setTimeout(() => stdinProcess.writeToStdin("Hello from the client!\n"), 500);
    setTimeout(() => stdinProcess.writeToStdin("Another line\n"), 1000);

    console.log("\n--- Python Stdin Output ---");
    const [stdin_stdout] = await Promise.all([
      stdinProcess.stdout.readAll(),
      stdinProcess.wait(),
    ]);
    console.log(`STDOUT:\n${stdin_stdout}`);
    console.log("--------------------------");
    console.log('Python script with stdin finished.');


  } catch (e) {
    console.error("\nAn error occurred:", e);
  } finally {
    if (sandbox) {
      console.log("\nTerminating sandbox...");
      sandbox.terminate();
      console.log("Sandbox terminated.");
    }
  }
}

main().catch(console.error);
