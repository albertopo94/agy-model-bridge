# Implementation Tasks: Daemon Lifecycle CLI & One-Line Distribution

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Medium

## Work Units

| Unit | Focus | Changes |
|---|---|---|
| 1 | PID file management | `bridge/daemon.py`, `tests/test_daemon.py` |
| 2 | Start, stop, status, dashboard APIs | `bridge/daemon.py`, `tests/test_daemon.py` |
| 3 | CLI subcommand wiring | `bridge/__main__.py`, `tests/test_daemon.py` |
| 4 | One-line installer script | `install.sh` |
| 5 | Full verification & docs | `README.md`, test suite |

---

## Phase 1: Daemon Process Control & PID Tracking
- [x] 1.1 [RED] Write unit tests in `tests/test_daemon.py` for `read_pid`, `write_pid`, `remove_pid`, and `is_pid_alive`.
- [x] 1.2 [GREEN] Implement PID management utilities in `bridge/daemon.py`.
- [x] 1.3 [REFACTOR] Ensure safe directory creation (`0o700`) and PID file permissions (`0o600`).

## Phase 2: Start, Stop, Status, and Dashboard APIs
- [x] 2.1 [RED] Write unit tests in `tests/test_daemon.py` for `start_daemon`, `stop_daemon`, `get_daemon_status`, and `open_dashboard`.
- [x] 2.2 [GREEN] Implement lifecycle methods in `bridge/daemon.py` with `webbrowser.open()` and `/api/status` polling.
- [x] 2.3 [REFACTOR] Harden against stale PID files, timeout handling, and headless environments.

## Phase 3: CLI Subcommand Dispatching
- [x] 3.1 [RED] Write unit tests in `tests/test_daemon.py` verifying CLI dispatches for `start`, `stop`, `status`, `dashboard` (and `open`).
- [x] 3.2 [GREEN] Wire subcommands in `bridge/__main__.py`.
- [x] 3.3 [REFACTOR] Polish CLI stdout feedback (PID, URL, emoji/checkmarks) and error messages.

## Phase 4: One-Line Installer Script
- [x] 4.1 Create `install.sh` supporting macOS and Linux with Python 3.10+ check, clone/symlink to `~/.local/bin/agy-bridge`, and PATH verification.
- [x] 4.2 Test `install.sh` syntax and permissions (`chmod +x install.sh`).

## Phase 5: Documentation & Regression Verification
- [x] 5.1 Update `README.md` with new `install.sh` instructions and daemon commands.
- [x] 5.2 Execute full test suite `python3 -m unittest discover -s tests -v` verifying 100% pass rate.
