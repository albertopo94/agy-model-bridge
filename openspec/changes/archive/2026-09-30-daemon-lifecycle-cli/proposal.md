# Proposal: Daemon Lifecycle CLI & One-Line Distribution

## Intent

Currently, running `agy-model-bridge` requires keeping a dedicated terminal window open, and onboarding requires manual repository cloning and local environment setup. This change provides background daemon lifecycle commands (`start`, `stop`, `status`, `dashboard`), automatic browser dashboard opening on startup, and a zero-dependency one-line installer script (`install.sh`).

## Scope

### In Scope
- `bridge/daemon.py`: Pure Python 3 background daemon management using PID files (`~/.agy-bridge/bridge.pid`) and process isolation.
- Subcommands wired into `bridge/__main__.py`:
  - `start [--port PORT] [--host HOST] [--no-open]`: Starts daemon, waits for `/api/status` health, opens default browser to `http://127.0.0.1:{port}/`, prints feedback.
  - `stop`: Sends graceful SIGTERM, cleans up PID file, confirms termination.
  - `status`: Checks PID liveness and queries `/api/status`, displaying runtime info, port, models count, auth status, and dashboard URL.
  - `dashboard` (alias `open`): Launches default web browser to active dashboard URL via `webbrowser.open()`.
- One-line installer `install.sh`:
  - Validates Python 3.10+ on macOS/Linux.
  - Installs/updates into `~/.local/share/agy-model-bridge` (or `~/.agy-bridge`).
  - Creates executable symlink `agy-bridge` in `~/.local/bin` (or `/usr/local/bin`).
  - Verifies PATH and displays onboarding instructions.
- Dashboard & Setup CLI Guidance Updates:
  - Mention `agy-bridge start` and `agy-bridge dashboard` in command completion messages.
- Full unit and integration tests in `tests/test_daemon.py`.

### Out of Scope
- Native macOS menu bar tray app GUI (kept zero-dependency terminal CLI).
- System-wide multi-user daemon services (runs in user space).
- External dependencies (pure Python 3 standard library only).

## Capabilities

### New Capabilities
- `daemon-lifecycle`: Background process lifecycle (`start`, `stop`, `status`, `dashboard`) with PID tracking and automatic browser launch.
- `installer`: One-line curl-to-bash installation and PATH symlinking.

### Modified Capabilities
- `client-setup`: Output post-setup guidance recommending `agy-bridge start` and `agy-bridge dashboard`.
- `gateway-dashboard`: Setup cards include daemon lifecycle commands.

## Approach

- Create `bridge/daemon.py` with:
  - `start_daemon(port, host, no_open, ...)`: Detaches process via `subprocess.Popen` with `start_new_session=True`, writes PID to `~/.agy-bridge/bridge.pid`, polls health endpoint, calls `webbrowser.open()`.
  - `stop_daemon()`: Reads PID, sends `signal.SIGTERM`, verifies termination, cleans up PID file.
  - `get_daemon_status()`: Inspects PID file and `/api/status`.
  - `open_dashboard()`: Opens browser or alerts if daemon is inactive.
- Update `bridge/__main__.py` with subcommands: `start`, `stop`, `status`, `dashboard`.
- Write `install.sh` in repository root.
- Add test suite in `tests/test_daemon.py`.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `bridge/daemon.py` | New | Process isolation, PID tracking, health probe, browser launch |
| `bridge/__main__.py` | Modified | Add `start`, `stop`, `status`, `dashboard` subcommands |
| `install.sh` | New | One-line installer script |
| `bridge/dashboard.py` | Modified | Update command references |
| `tests/test_daemon.py` | New | Tests for daemon start/stop/status/dashboard |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Stale PID file after unexpected reboot | Low | Verify PID belongs to running `bridge` process before reporting active |
| Port conflict during start | Low | Check port availability or existing daemon before launching |
| Browser fails to open in headless/SSH environment | Low | Catch `webbrowser.Error` gracefully without aborting daemon startup |

## Rollback Plan

Revert git commit. Stop any running daemon process via `kill $(cat ~/.agy-bridge/bridge.pid 2>/dev/null)`.

## Dependencies

- Python 3.10+ standard library (`subprocess`, `os`, `signal`, `urllib.request`, `webbrowser`, `time`, `pathlib`).
- Zero third-party dependencies.

## Success Criteria

- [ ] `agy-bridge start` launches daemon in background and opens browser automatically.
- [ ] `agy-bridge stop` stops daemon cleanly.
- [ ] `agy-bridge status` reports accurate PID, port, and health.
- [ ] `agy-bridge dashboard` opens default browser to active dashboard URL.
- [ ] `install.sh` installs executable and verifies requirements.
- [ ] Full test suite passes 100%.
