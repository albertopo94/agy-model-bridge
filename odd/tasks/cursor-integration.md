# Feature Tasks: Cursor Integration

## Context
Integrate Cursor CLI (`agent`) into AGY Model Bridge.
- **Phase 1**: Account usage tracking via macOS Keychain (`service="cursor-access-token"`), `/api/cursor/quota` endpoint, and dashboard card under Antigravity. (COMPLETED)
- **Phase 2**: Cursor Upstream Model Gateway via `agent -p` in background for `/v1/chat/completions` and `/v1/messages`. (COMPLETED)
- **Phase 3**: Multi-Provider Client Setup, Model Labeling (`[Cursor - Free]`, `[Cursor - Pro]`), Tooltip Note for Free Tier, and Dashboard Multi-Provider Tabs. (IN PROGRESS)

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

## Phase 2: Cursor Upstream Model Gateway (Completed)
- [x] 6.1 [RED] Write unit tests in `tests/test_cursor_backend.py`
- [x] 6.2 [GREEN] Implement `bridge/cursor_backend.py`
- [x] 7.1 [RED] Write unit tests for model catalog discovery
- [x] 7.2 [GREEN] Wire `CursorBackend.list_models()` into `GET /v1/models`
- [x] 8.1 [RED] Write unit tests in `tests/test_server.py` for `/v1/chat/completions` & `/v1/messages`
- [x] 8.2 [GREEN] Implement request dispatch in `bridge/server.py`
- [x] 9.1 Run full test suite (`1004 tests passing`)
- [x] 9.2 Work-unit commit `4a0f7d3`

---

## Phase 3: Multi-Provider Setup CLI, Model Labels & Dashboard Tabs (In Progress)

### 10. Model Labels & Free Tier Notice in `bridge/cursor_backend.py` & Dashboard (TDD)
- [ ] 10.1 [RED] Write unit tests in `tests/test_cursor_backend.py` for model display names: `cursor/auto` -> `Auto [Cursor - Free]`, named models -> `<Name> [Cursor - Pro]`.
- [ ] 10.2 [GREEN] Update `bridge/cursor_backend.py` with friendly display labels and free/pro badge tags.
- [ ] 10.3 [GREEN] Add Free tier tooltip / notice in `bridge/dashboard.py` on Cursor tabs explaining that Cursor Free plan only allows `auto`.

### 11. Multi-Provider Client Setup CLI Integration (`setup-*`) (TDD)
- [ ] 11.1 [RED] Write unit tests in `tests/test_setup.py` for `GentleShellConfigurator` and `PiConfigurator` supporting `provider` (`"agy"`, `"cursor"`, `"all"`), verifying `models.json` registers `DEFAULT_CURSOR_MODELS` alongside AGY.
- [ ] 11.2 [GREEN] Implement `DEFAULT_CURSOR_MODELS` in `bridge/setup/pi_gentle.py` and support multi-provider setup in `PiConfigurator` and `GentleShellConfigurator`.
- [ ] 11.3 [RED] Write unit tests in `tests/test_setup.py` for `ClaudeConfigurator`, `CodexConfigurator`, `OpenCodeConfigurator`, `OpenClawConfigurator`, `HermesConfigurator` supporting `provider` (`"agy"`, `"cursor"`, `"all"`).
- [ ] 11.4 [GREEN] Implement multi-provider support in client configurators and add `--provider` choices to `bridge/cli/setup.py`.

### 12. Dashboard Cards Segmented Provider Controls (TDD)
- [ ] 12.1 [RED] Write unit tests in `tests/test_dashboard.py` asserting Gentle Shell has 4 tabs (`AGY`, `Cursor`, `Todos`, `FreeLLMAPI`), and other cards have 3 tabs (`AGY`, `Cursor`, `Todos`).
- [ ] 12.2 [GREEN] Update `CLIENT_CARDS` in `bridge/dashboard.py` with segmented provider tabs, auto commands, and manual snippets.

### 13. Documentation, Verification & Work-Unit Commit
- [x] 13.1 Update `README.md` with complete documentation for Cursor quota, upstream model gateway, and multi-provider client setups.
- [x] 13.2 Run full test suite, linter, typecheck.
- [x] 13.3 Create clean work-unit commit on `albertopo94/hammerhead` (`9be0865`).
