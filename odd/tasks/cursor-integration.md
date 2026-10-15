# Feature Tasks: Cursor Integration

## Context
Integrate Cursor CLI (`agent`) into AGY Model Bridge.
- **Phase 1**: Account usage tracking via macOS Keychain (`service="cursor-access-token"`), `/api/cursor/quota` endpoint, and dashboard card under Antigravity. (COMPLETED)
- **Phase 2**: Cursor Upstream Model Gateway. Expose models from Cursor subscription (`gpt-5.3-codex`, `composer-2.5`, `claude-opus-5-5-high`, `grok-4.7`, etc.) via standard `/v1/chat/completions`, `/v1/messages`, and `/v1/models` using `agent -p` in background.

---

## Phase 1 (Completed)
- [x] 1.1 [RED] Write unit tests in `tests/test_cursor_auth.py`
- [x] 1.2 [GREEN] Implement `bridge/cursor_auth.py`
- [x] 2.1 [RED] Write unit tests in `tests/test_cursor_quota.py`
- [x] 2.2 [GREEN] Implement `bridge/cursor_quota.py`
- [x] 3.1 [RED] Write unit tests in `tests/test_server.py` for `GET /api/cursor/quota`
- [x] 3.2 [GREEN] Wire `cursor_quota_provider` into `ServerContext` and `bridge/server.py`
- [x] 4.1 [RED] Write unit tests in `tests/test_dashboard.py` for Cursor Quota Card
- [x] 4.2 [GREEN] Update `bridge/dashboard.py` to add Cursor Quota Card under Antigravity
- [x] 5.1 Run full test suite (`988 tests passing`)
- [x] 5.2 Work-unit commit `50e6b69` and `0d379cf`

---

## Phase 2: Cursor Upstream Model Gateway (In Progress)

### 6. Prompt & Message Converter and Cursor Subprocess Runner (TDD)
- [x] 6.1 [RED] Write unit tests in `tests/test_cursor_backend.py` for:
  - `messages_to_prompt` (single user message, multi-turn `[System]`/`[User]`/`[Assistant]`, list content parts).
  - `resolve_cursor_model` (`cursor/gpt-5.3-codex` -> `gpt-5.3-codex`, `cursor-gpt-5.3-codex` -> `gpt-5.3-codex`, `auto`).
  - Parsing Cursor CLI `stream-json` messages (`system`, `assistant` text diffs, `result`).
  - Subprocess runner invoking `agent -p --output-format stream-json --stream-partial-output --yolo` with prompt piped via stdin.
- [x] 6.2 [GREEN] Implement `bridge/cursor_backend.py` with pure standard library (`subprocess`, `threading`, `json`).

### 7. Model Discovery & Combined Catalog in `GET /v1/models` (TDD)
- [x] 7.1 [RED] Write unit tests for model catalog discovery via `agent models` with static fallback, asserting Cursor models appear in `GET /v1/models` with `owned_by: "cursor"`.
- [x] 7.2 [GREEN] Wire `CursorBackend.list_models()` into `GET /v1/models` in `bridge/server.py`.

### 8. Server Upstream Routing to Cursor (`/v1/chat/completions` & `/v1/messages`) (TDD)
- [x] 8.1 [RED] Write unit tests in `tests/test_server.py` verifying requests with `cursor/*` or Cursor-specific models route to `CursorBackend` in streaming SSE and non-streaming modes.
- [x] 8.2 [GREEN] Implement request dispatch in `bridge/server.py` for chat completions and messages.

### 9. Verification & Work-Unit Commit
- [x] 9.1 Run full test suite, linter, typecheck.
- [x] 9.2 Create work-unit commit on `albertopo94/hammerhead` (`2d0cb7e`).
