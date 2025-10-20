/**
 * This example demonstrates the checkpoint and restore functionality.
 *
 * It performs the following steps:
 * 1. Creates a new sandbox on one server instance.
 * 2. Executes a command to create a file in the sandbox.
 * 3. Checkpoints the sandbox.
 * 4. Attaches to the same sandbox ID from a different client, potentially
 *    on a different server instance, which triggers a restore.
 * 5. Executes a command to verify that the file exists.
 *
 * SERVER-SIDE REQUIREMENTS:
 * To run this example, the Cloud Run service must be deployed with a persistent
 * volume (e.g., a GCS bucket) and the `CHECKPOINT_AND_RESTORE_PATH` environment
 * variable set to the mount path of that volume.
 *
 * This script expects the URLs of your deployed Cloud Run services to be
 * set in environment variables. For a local test, you can use the same URL for both.
 *
 * The WebSocket URLs should be in the format: wss://<your-cloud-run-url>
 *
 * To run this example:
 * 1. Make sure you have ts-node installed (`npm install -g ts-node`).
 * 2. Set the environment variables:
 *    `export CLOUD_RUN_URL_CHECKPOINT="wss://your-service-a-url.run.app"`
 *    `export CLOUD_RUN_URL_RESTORE="wss://your-service-b-url.run.app"`
 * 3. Run the script from the root of the repository:
 *    `npx ts-node example/checkpoint.ts`
 */
import { Sandbox } from '../clients/js/src/sandbox';

async function main() {
  const urlCheckpoint = process.env.CLOUD_RUN_URL_CHECKPOINT;
  const urlRestore = process.env.CLOUD_RUN_URL_RESTORE;

  if (!urlCheckpoint || !urlRestore) {
    console.error("Error: Please set the CLOUD_RUN_URL_CHECKPOINT and CLOUD_RUN_URL_RESTORE environment variables.");
    console.error("Example: export CLOUD_RUN_URL_CHECKPOINT=\"wss://your-service-a-url.run.app\"");
    console.error("         export CLOUD_RUN_URL_RESTORE=\"wss://your-service-b-url.run.app\"");
    return;
  }

  console.log('--- Checkpoint and Restore Example ---');
  console.log(`Using Checkpoint URL: ${urlCheckpoint}`);
  console.log(`Using Restore URL: ${urlRestore}`);

  let sandbox: Sandbox | null = null;
  let sandboxId: string | null = null;

  try {
    // 1. Create a new sandbox
    console.log('\n--- Step 1: Creating Sandbox ---');
    sandbox = await Sandbox.create(urlCheckpoint, {
      enableSandboxCheckpoint: true,
    });
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
    sandbox = await Sandbox.attach(urlRestore, sandboxId!);
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
