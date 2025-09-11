#!/usr/bin/env ts-node
/**
 * An example of creating a pseudo-interactive shell in the sandbox.
 *
 * This script demonstrates how to pipe stdin, stdout, and stderr to create
 * a basic interactive shell experience.
 *
 * Note: This is not a true TTY and has limitations. For example, it is
 * line-buffered, so features like tab-completion will not work.
 *
 * To run this example:
 * 1. Make sure you have ts-node installed (`npm install -g ts-node`).
 * 2. Set the environment variable:
 *    `export CLOUD_RUN_URL="wss://your-service-url.run.app"
 * 3. Run the script from the root of the repository:
 *    `ts-node example/interactive_shell.ts`
 */
import { Sandbox } from '../clients/js/src/sandbox';

async function main() {
  const url = process.env.SANDBOX_WSS;
  if (!url) {
    console.error("Error: Please set the CLOUD_RUN_URL environment variable.");
    return;
  }

  let sandbox: Sandbox | undefined;
  try {
    sandbox = await Sandbox.create(url);
    console.log(`Connected to sandbox: ${sandbox.sandboxId}`);
    console.log("Starting interactive shell... (type 'exit' to quit)");

    const shellProcess = await sandbox.exec("export PS1='sandbox> '; /bin/bash -i", 'bash');

    // Pipe stdin
    process.stdin.on('data', (data) => {
      shellProcess.writeToStdin(data.toString());
    });

    // Pipe stdout and stderr
    shellProcess.stdout.on('data', (data) => {
      process.stdout.write(data);
    });
    shellProcess.stderr.on('data', (data) => {
      process.stderr.write(data);
    });

    // Handle process exit
    await shellProcess.wait();

  } catch (e) {
    console.error("\nAn error occurred:", e);
  } finally {
    if (sandbox) {
      sandbox.terminate();
    }
    // Exit the process, otherwise the stdin listener will keep it alive.
    process.exit();
  }
}

main().catch(console.error);
