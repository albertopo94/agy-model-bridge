# Capability: Daemon Lifecycle Management

## Overview

Provides non-blocking background daemon execution, PID file tracking, health check verification, and browser integration for Antigravity Model Bridge without locking the user's terminal.

---

### Requirement: Daemon Start

The system MUST provide a `start` command to run the bridge server detached in the background.

#### Scenario: Successful start in background with browser launch
- **Given** no bridge daemon is currently running
- **When** the user executes `agy-bridge start`
- **Then** the bridge process MUST start detached from the current terminal session
- **And** the process PID MUST be written to `~/.agy-bridge/bridge.pid`
- **And** the command MUST poll `/api/status` until the server responds healthy (or timeout after 5 seconds)
- **And** the default web browser MUST be opened to `http://127.0.0.1:24980/`
- **And** stdout MUST confirm: PID, listening port, and dashboard URL

#### Scenario: Start with --no-open flag
- **Given** no bridge daemon is currently running
- **When** the user executes `agy-bridge start --no-open`
- **Then** the bridge process MUST start in the background
- **And** the browser MUST NOT be opened
- **And** stdout MUST print the dashboard URL

#### Scenario: Start when already running
- **Given** a bridge daemon is already running on the configured port
- **When** the user executes `agy-bridge start`
- **Then** the command MUST NOT launch a duplicate process
- **And** stdout MUST report that the bridge is already running with its existing PID and dashboard URL

---

### Requirement: Daemon Stop

The system MUST provide a `stop` command to terminate the background bridge daemon cleanly.

#### Scenario: Clean stop of active daemon
- **Given** a bridge daemon is running with its PID recorded in `~/.agy-bridge/bridge.pid`
- **When** the user executes `agy-bridge stop`
- **Then** a `SIGTERM` signal MUST be sent to the process
- **And** the command MUST wait for the process to exit
- **And** the PID file MUST be removed
- **And** stdout MUST confirm that the bridge has been stopped

#### Scenario: Stop when not running
- **Given** no bridge daemon is running
- **When** the user executes `agy-bridge stop`
- **Then** stdout MUST inform the user that the bridge is not running
- **And** the exit code MUST be 0

---

### Requirement: Daemon Status

The system MUST provide a `status` command to query runtime state.

#### Scenario: Query status while running
- **Given** a bridge daemon is running on port 24980
- **When** the user executes `agy-bridge status`
- **Then** the command MUST probe `/api/status`
- **And** stdout MUST display: PID, host:port, auth status, discovered models count, and dashboard link

#### Scenario: Query status while stopped
- **Given** no bridge daemon is running
- **When** the user executes `agy-bridge status`
- **Then** stdout MUST indicate that the bridge is stopped
- **And** stdout MUST suggest running `agy-bridge start`

---

### Requirement: Dashboard Open

The system MUST provide a `dashboard` command (alias `open`) to launch the web interface.

#### Scenario: Open dashboard while bridge is running
- **Given** the bridge daemon is running
- **When** the user executes `agy-bridge dashboard`
- **Then** the default web browser MUST open `http://127.0.0.1:24980/`
- **And** stdout MUST confirm the action

#### Scenario: Open dashboard while bridge is stopped
- **Given** the bridge daemon is not running
- **When** the user executes `agy-bridge dashboard`
- **Then** the command MUST notify the user that the bridge is stopped
- **And** stdout MUST prompt the user to run `agy-bridge start`
