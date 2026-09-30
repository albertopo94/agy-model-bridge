# Capability: One-Line Installer

## Overview

Provides a zero-friction, one-line installer script (`install.sh`) that installs `agy-model-bridge` globally without requiring manual Git management or Python virtual environment setup.

---

### Requirement: Automated Installation Script

The repository MUST provide a POSIX-compatible shell script `install.sh` executable via `curl -fsSL ... | bash`.

#### Scenario: Clean installation on macOS or Linux
- **Given** macOS or Linux with `python3` (>= 3.10) installed
- **When** the user executes `curl -fsSL https://.../install.sh | bash`
- **Then** the installer MUST clone or update the repository to `~/.local/share/agy-model-bridge` (or `~/.agy-bridge`)
- **And** the installer MUST create an executable wrapper/symlink `agy-bridge` in `~/.local/bin` (or `/usr/local/bin`)
- **And** the installer MUST verify whether `~/.local/bin` is in the user's `PATH` and instruct the user if not
- **And** stdout MUST display a clear welcome message with immediate next steps:
  - `agy-bridge start`
  - `agy-bridge setup-claude`
  - `agy-bridge setup-codex`

#### Scenario: Incompatible Python version check
- **Given** a system with Python < 3.10 or missing `python3`
- **When** the user executes `install.sh`
- **Then** the installer MUST abort with an informative error message explaining that Python 3.10+ is required
- **And** the exit code MUST be non-zero
