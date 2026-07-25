# ADBLab Agent Skill Contract v0.1 (Draft)

## 1) Purpose
Define a stable internal contract for integrating external / third-party skills into ADBLab.

## 2) Core Invocation API

```python
def run_skill(name: str, payload: dict, context: dict) -> dict:
    """
    Run one logical skill and return a unified result payload.
    """
```

## 3) Standard Input/Output Model

### 3.1 Input

```json
{
  "name": "adb.push_file",
  "payload": {
    "device_id": "string",
    "local_path": "string",
    "remote_path": "string"
  },
  "context": {
    "request_id": "string",
    "ui_thread": "main",
    "trace_id": "string",
    "timeout_ms": 120000
  }
}
```

### 3.2 Output

```json
{
  "ok": true,
  "request_id": "string",
  "name": "adb.push_file",
  "result": {},
  "artifacts": [
    {
      "type": "log",
      "path": "string"
    }
  ],
  "error": {
    "code": "string",
    "message": "string",
    "details": {}
  },
  "telemetry": {
    "elapsed_ms": 0,
    "events": []
  }
}
```

## 4) Error Code Baseline

- `SKILL_NOT_FOUND`
- `INVALID_INPUT`
- `TIMEOUT`
- `DEVICE_OFFLINE`
- `PERMISSION_DENIED`
- `EXEC_FAIL`
- `CANCELLED`

## 5) Threading Rule

- `run_skill` must never run blocking tasks on the Qt main thread.
- Long-running execution should be executed in a worker thread or external process.
- All UI updates must be posted through existing Qt signal paths.

## 6) Logging Rule

- Debug output from skills and related pipelines should be emitted only through debug logger channels.
- Operational logs shown in main UI should be limited to user-facing status, errors, and completion states.
- A dedicated trace id should be attached to all skill logs.

## 7) Lifecycle Rule

- Support `cancel` signal from UI/operation supervisor.
- Support `finally` cleanup hook:
  - kill started subprocesses (where safe)
  - close opened handles
  - flush logs

