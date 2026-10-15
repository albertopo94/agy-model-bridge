# Feature Tasks: Cursor ACP Integration (Phase 4: Instant In-Process Cursor Streaming)

## Context
Cursor CLI `agent -p` mode suffers from a ~20-40 second cold start overhead per request due to Node runtime instantiation, environment inspection, and workspace scanning. Cursor's official solution for editors and clients is the Agent Client Protocol (ACP), invoked via `agent --trust --yolo acp`, which keeps a warm Node.js process alive in the background communicating via stdio JSON-RPC 2.0. This achieves prompt responses in 2-5 seconds (a 10-20x speedup).

## Tasks

### 1. Cursor ACP Client Subsystem (TDD)
- [ ] 1.1 [RED] Write unit tests in `tests/test_cursor_acp.py` for `CursorAcpClient`:
  - Process lifecycle (`start`, `stop`, `restart`, `is_alive`).
  - Handshake (`initialize`, `authenticate` with `cursor_login`).
  - Session creation (`session/new`).
  - Auto-responding to `session/request_permission` notifications (`allow-once`).
  - Streaming prompt chunks (`session/prompt` and `session/update` -> `agent_message_chunk`).
  - Timeout and graceful process recovery on crash.
- [ ] 1.2 [GREEN] Implement `bridge/cursor_acp.py` using pure standard library (`subprocess`, `threading`, `json`, `queue`).

### 2. Integration into CursorBackend with Fallback (TDD)
- [ ] 2.1 [RED] Write unit tests in `tests/test_cursor_backend.py` verifying `CursorBackend` uses ACP by default for streaming and non-streaming requests, falling back to `agent -p` if ACP is unavailable or disabled.
- [ ] 2.2 [GREEN] Wire `CursorAcpClient` into `CursorBackend.stream_chat()` and `generate_chat()`.

### 3. Live Verification & Performance Benchmark
- [ ] 3.1 Verify live `curl` request against `http://127.0.0.1:24980/v1/chat/completions` responds in <5s instead of 40s.
- [ ] 3.2 Run complete test suite (1010+ tests) to guarantee 100% pass rate.

### 4. Release v0.27.0 & Documentation
- [x] 4.1 Synchronize version `0.27.0` across `bridge/__init__.py`, `pyproject.toml`, `install.sh`, and tests.
- [x] 4.2 Document Cursor ACP instant execution in `README.md`.
- [ ] 4.3 Create work-unit commits, merge to `main`, create tag `v0.27.0`, push, and publish GitHub Release.
