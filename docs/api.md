# API and Configuration

This document details the environment variables that can be used to configure the
gVisor sandbox and provides examples of how to use the API.

## Environment Variables

The following environment variables can be used to configure the gVisor sandbox:

| Variable | Description | Default |
|---|---|---|
| `LOG_LEVEL` | The log level for the application. Can be `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. | `INFO` |
| `CHECKPOINT_AND_RESTORE_PATH` | The path to a directory where sandboxes can be checkpointed and restored from (e.g., a mounted GCS volume). If not set, this functionality is disabled. | (not set) |
| `RUNSC_USE_SUDO` | Set to `true` to run `runsc` commands with `sudo`. | `false` |
| `RUNSC_ROOTLESS` | Set to `true` to run `runsc` in rootless mode. | `false` |
| `RUNSC_ROOT_DIR_BASE` | The base directory for sandbox root directories. | `/tmp` |
| `RUNSC_BUNDLE_DIR_BASE` | The base directory for OCI bundles. | `/tmp` |
| `RUNSC_IGNORE_CGROUPS` | Set to `true` to ignore cgroup errors. | `true` |
| `RUNSC_PLATFORM` | The gVisor platform to use (e.g., `ptrace`, `kvm`). | `ptrace` |
| `RUNSC_DISABLE_NETWORKING` | Set to `true` to disable networking for the sandbox. | `false` |
| `RUNSC_READONLY_FILESYSTEM` | Set to `true` to make the sandbox filesystem readonly. | `false` |
| `GVISOR_DEBUG` | Set to `true` to enable gVisor's debug logging. | `false` |
| `GVISOR_STRACE` | Set to `true` to enable strace for sandboxed processes. | `false` |
| `GVISOR_LOG_PACEKTS` | Set to `true` to enable packets logging for sandboxed processes. | `false` |
| `GVISOR_DEBUG_LOG_DIR` | The base directory for gVisor's debug logs. | `/tmp/runsc` |

## API Usage

### Execute Code

You can execute Python or Bash code by sending a `POST` request to the `/execute`
endpoint. The code should be sent as the raw request body, and the `language`
query parameter can be used to specify the language.

Currently, the only supported languages are `python` and `bash`.

**Example: Execute Python Code**

```bash
curl -s -X POST -H "Content-Type: text/plain" --data-binary @example/test_hello.py https://<YOUR_SERVICE_URL>/execute?language=python
```

**Example: Execute Bash Code**

```bash
curl -s -X POST -H "Content-Type: text/plain" --data "echo 'hello from bash'" https://<YOUR_SERVICE_URL>/execute?language=bash
```
