# Design: Daemon Lifecycle CLI & One-Line Distribution

## Architecture Overview

```mermaid
flowchart TD
    User["Developer / User"] -->|agy-bridge start| CLI["bridge/__main__.py"]
    CLI -->|start_daemon()| DaemonMgr["bridge/daemon.py"]
    DaemonMgr -->|subprocess.Popen start_new_session=True| DaemonProc["bridge (Background Process)"]
    DaemonProc -->|Writes PID| PIDFile["~/.agy-bridge/bridge.pid"]
    DaemonProc -->|Logs output| LogFile["~/.agy-bridge/bridge.log"]
    DaemonMgr -->|Poll health /api/status| DaemonProc
    DaemonMgr -->|webbrowser.open()| Browser["Default Web Browser (Dashboard)"]
```

## Sequence Diagrams

### 1. `agy-bridge start` Flow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as agy-bridge start
    participant Daemon as bridge.daemon
    participant OS as Subprocess (OS)
    participant Server as HTTP Server (:24980)
    participant Browser as Default Browser

    User->>CLI: agy-bridge start [--no-open]
    CLI->>Daemon: start_daemon(host, port, no_open)
    Daemon->>Daemon: Check existing PID & port
    alt Already running
        Daemon-->>CLI: Return existing PID
        CLI-->>User: "Already running at http://127.0.0.1:24980/"
    else Not running
        Daemon->>OS: Popen([python3, -m, bridge], start_new_session=True)
        OS-->>Daemon: pid
        Daemon->>Daemon: Write pid to ~/.agy-bridge/bridge.pid
        loop Up to 5s poll
            Daemon->>Server: GET /api/status
            Server-->>Daemon: HTTP 200 {status: ok}
        end
        opt no_open is False
            Daemon->>Browser: webbrowser.open("http://127.0.0.1:24980/")
        end
        Daemon-->>CLI: {running: True, pid: pid, port: 24980}
        CLI-->>User: ✔ Running in background (PID xxxxx)\n➜ Dashboard: http://127.0.0.1:24980/
    end
```

### 2. `agy-bridge stop` Flow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as agy-bridge stop
    participant Daemon as bridge.daemon
    participant Server as Background Server Process

    User->>CLI: agy-bridge stop
    CLI->>Daemon: stop_daemon()
    Daemon->>Daemon: Read ~/.agy-bridge/bridge.pid
    alt PID found & alive
        Daemon->>Server: os.kill(pid, SIGTERM)
        loop Up to 5s
            Daemon->>Daemon: Check os.kill(pid, 0)
        end
        Daemon->>Daemon: Unlink PID file
        Daemon-->>CLI: Stopped successfully
        CLI-->>User: ✔ AGY Model Bridge stopped
    else No PID or not running
        Daemon-->>CLI: Not running
        CLI-->>User: AGY Model Bridge is not running
    end
```

## Key Decisions and Rationale

1. **Pure Python 3 standard library daemonization:**  
   Using `subprocess.Popen` with `start_new_session=True` (and redirection to `~/.agy-bridge/bridge.log`) detaches the background process cleanly from the controlling terminal across all POSIX systems (macOS and Linux) without requiring external packages like `daemonize` or `psutil`.

2. **PID file storage in `~/.agy-bridge/`:**  
   Standard XDG/user-space directory path. Ensures permissions `0o700` on directory and `0o600` on PID file to isolate user state.

3. **`webbrowser.open()` for zero-friction feedback:**  
   Using Python's built-in `webbrowser.open()` provides seamless cross-browser launching on macOS (Safari, Chrome, Arc, Brave) without spawning shell scripts or AppleScript dependencies.

4. **One-line installer `install.sh`:**  
   Clones into `~/.local/share/agy-model-bridge` and creates an executable launcher script in `~/.local/bin/agy-bridge`. Automatically prompts the user if `~/.local/bin` is not yet on their `PATH`.
