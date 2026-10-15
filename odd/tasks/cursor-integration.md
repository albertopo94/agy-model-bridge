# Feature Tasks: Cursor Integration (Phase 1: Quota Tracking & Dashboard Card)

## Context
Integrate Cursor account usage tracking into AGY Model Bridge. Extract credentials from macOS Keychain (`service="cursor-access-token"`, `account="cursor-user"`) or Cursor CLI (`agent status --format json`), fetch quota details from `https://cursor.com/api/usage-summary`, expose `/api/cursor/quota`, and render a dedicated Cursor Quota Card directly beneath the Antigravity card in the dashboard.

## Tasks

### 1. Cursor Auth & Keychain Extraction (TDD)
- [x] 1.1 [RED] Write unit tests in `tests/test_cursor_auth.py` for reading `cursor-access-token` from macOS Keychain, decoding JWT `sub`, building `WorkosCursorSessionToken` cookie, and handling errors/missing auth.
- [x] 1.2 [GREEN] Implement `bridge/cursor_auth.py` with `get_cursor_session_cookie()` and `read_cursor_auth_token()` with TTL cache and zero external dependencies.

### 2. Cursor Quota Provider & Usage Parser (TDD)
- [x] 2.1 [RED] Write unit tests in `tests/test_cursor_quota.py` for parsing `https://cursor.com/api/usage-summary` JSON response into quota snapshot with buckets (`Cursor Models`, `Other Models`, `Plan`, reset date, membership type).
- [x] 2.2 [GREEN] Implement `bridge/cursor_quota.py` with `CursorQuotaProvider`, single-flight lock, 60s TTL cache, stale-on-error resilience.

### 3. Server Endpoint `GET /api/cursor/quota` (TDD)
- [x] 3.1 [RED] Write unit tests in `tests/test_server.py` verifying `GET /api/cursor/quota` returns 200 with snapshot and handles `?refresh=1`.
- [x] 3.2 [GREEN] Wire `cursor_quota_provider` into `ServerContext` and `bridge/server.py`.

### 4. Dashboard UI Card beneath Antigravity (TDD)
- [x] 4.1 [RED] Write unit tests in `tests/test_dashboard.py` asserting Cursor Quota Card container, status badges, bars, and script hooks are present.
- [x] 4.2 [GREEN] Update `bridge/dashboard.py` to add the Cursor Quota Card under Antigravity, including CSS styling, JS fetch logic, auto-refresh, and bilingual support.

### 5. Verification & Work-Unit Commit
- [x] 5.1 Run full test suite (`python3 -m unittest discover -s tests -v`), linter, and type checks.
- [x] 5.2 Create clean work-unit commit on `albertopo94/hammerhead` (`b855d46`).
