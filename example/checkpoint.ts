/**
 * This example demonstrates the checkpoint and restore functionality of the Cloud Run Sandbox.
 *
 * It performs the following steps:
 * 1. Creates a new sandbox with checkpointing enabled.
 * 2. Executes a command to write a file to the sandbox's filesystem.
 * 3. Checkpoints the sandbox, persisting its state.
 * 4. Attaches to the previously checkpointed sandbox.
 * 5. Executes a command to read the file, verifying that the state was restored.
 *
 * SERVER-SIDE REQUIREMENTS:
 * To run this example, the Cloud Run service must be deployed with a persistent
 * volume (e.g., a GCS bucket) and the `CHECKPOINT_AND_RESTORE_PATH` environment
 * variable set to the mount path of that volume.
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
 *    `ts-node example/checkpoint.ts`
 *
 * Full command used for successful run:
 * `export CLOUD_RUN_URL="wss://sandbox-26651309217.us-central1.run.app" && npx ts-node example/checkpoint.ts`
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
  let sandboxId: string | null = null;

  try {
    // 1. Create a new sandbox with checkpointing enabled
    console.log("Creating a new sandbox with checkpointing enabled...");
    sandbox = await Sandbox.create(url, { enableCheckpoint: true });
    sandboxId = sandbox.sandboxId;
    console.log(`Successfully created sandbox with ID: ${sandboxId}`);

    // 2. Write a file to the sandbox's filesystem
    const filename = `/tmp/testfile_${Date.now()}.txt`;
    const content = "Hello from the original sandbox!";
    console.log(`\nExecuting command to write to ${filename}...`);
    const writeFileProcess = await sandbox.exec("bash", `echo "${content}" > ${filename}`);
    await writeFileProcess.wait();
    console.log("File written successfully.");

    // 3. Checkpoint the sandbox
    console.log("\nCheckpointing sandbox...");
    await sandbox.checkpoint();
    console.log("Sandbox checkpointed successfully. The connection is now closed.");

    // At this point, the original sandbox object is no longer usable.
    // The server has closed the connection.

    // 4. Attach to the checkpointed sandbox
    console.log(`\nAttaching to sandbox ${sandboxId}...`);
    sandbox = await Sandbox.attach(url, sandboxId!); 
    console.log("Successfully attached to the restored sandbox.");

    // 5. Verify the state by reading the file
    console.log(`\nExecuting command to read from ${filename}...`);
    const readFileProcess = await sandbox.exec("bash", `cat ${filename}`);
    const stdout = await readFileProcess.stdout.readAll();
    await readFileProcess.wait();

    console.log("\n--- Restored Sandbox Output ---");
    console.log(`Read from file: ${stdout.trim()}`);
    console.log("-----------------------------");

    if (stdout.trim() === content) {
      console.log("\n✅ Success: The file content was restored correctly!");
    } else {
      console.error("\n❌ Failure: The file content did not match.");
    }
  } catch (e) {
    console.error("\nAn error occurred:", e);
  } finally {
    if (sandbox && sandbox.sandboxId) {
      console.log("\nTerminating sandbox...");
      sandbox.terminate();
      console.log("Sandbox terminated.");
    }
  }
}

main().catch(console.error);
