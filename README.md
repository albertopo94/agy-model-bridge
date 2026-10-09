# AGY Model Bridge

Zero-dependency, pure Python 3 local AI gateway that bridges the Google Cloud Code Assist backend (`daily-cloudcode-pa.googleapis.com`) to standard client protocols, providing native model access for **Claude Code**, **Codex CLI**, **Hermes Agent**, **OpenCode**, **OpenClaw**, **Cursor**, **Pi**, **Gentle Shell**, and **FreeLLMAPI**.

---

## Features

- **Zero External Dependencies**: Built entirely using the Python 3 standard library (`http.server`, `urllib.request`, `subprocess`, `json`, `base64`, `threading`, `time`). No `pip install`, no virtual environment, no Node.js required.
- **Multi-Protocol Gateway**:
  - `GET /` — Self-contained dark-mode dashboard (Geist/Vercel styling) with live Keychain auth badges, model count, and one-click copyable setup cards.
  - `GET /v1/models` — Dynamic model catalog discovered directly from upstream Cloud Code Assist with Codex serde compatibility (`data`, `models`, `slug`, `display_name`).
  - `POST /v1/chat/completions` — OpenAI Chat Completions API with full streaming (SSE `text/event-stream`) and non-streaming support (for FreeLLMAPI, Hermes Agent, OpenCode, OpenClaw, Cursor, Pi, Gentle Shell, Aider).
  - `POST /v1/responses` — OpenAI Responses API shim for Codex CLI (`wire_api = "responses"`).
  - `POST /v1/messages` — Anthropic Messages API shim with dynamic SSE stream mapping (`thinking_delta`, `text_delta`, `tool_use`, `input_json_delta`), recursive OpenAPI 3.0 schema sanitization, and full tool calling for Claude Code CLI.
- **Built-in Setup CLI**: Native subcommands (`setup-claude`, `setup-codex`, `setup-hermes`, `setup-opencode`, `setup-openclaw`, `setup-cursor`, `setup-pi`, `setup-gentle-shell`) that surgically configure client environments with atomic writes, file permissions `0o600`, and automatic timestamped backups.
- **Automatic Local API Key Security**: Automatically generates a persistent random API key stored at `~/.agy-bridge/api_key` (`0600` permissions) to protect `/v1/*` gateway endpoints against cross-origin access.
- **macOS Keychain OAuth Integration**: Seamlessly extracts Google OAuth credentials stored by Antigravity in Keychain (`service="gemini"`, `account="antigravity"`) with thread-safe TTL caching and automatic 401 re-read.
- **Adaptive Thinking & Model Aliasing**: Intelligently resolves `gemini-3.8-flash-high` / `auto` to upstream `gemini-3.8-flash-tiered`, automatically configuring reasoning levels (`HIGH`, `MEDIUM`, `LOW`) and token budgets.

---

## Requirements

- **Operating System**: macOS (Apple Silicon or Intel). *Automatic Keychain OAuth extraction is macOS-native; Linux/POSIX systems can run the bridge by passing `--project` and managing credentials.*
- **Python**: 3.10+
- **Google Antigravity**: Installed and logged in (`agy login` or open Antigravity application).

---

## Important macOS Setup Notes

### 1. Keychain Permission Prompt (First Run Only)
The first time the bridge accesses the Keychain item stored by Antigravity, macOS may display a system security dialog:
> *"python wants to access key 'antigravity' in your keychain. Enter your password to allow this."*

Click **"Always Allow"** (or enter your Mac login password) so the bridge can read the active Antigravity session without prompting on every restart.

### 2. Session & Token Freshness
The bridge reads the active OAuth token managed by Antigravity. If you have not opened Antigravity in several days and the access token expires, the dashboard header badge will display:
> `⚠️ Expired — Open Antigravity to refresh`

Simply launch the Antigravity application so it can renew its credentials in Keychain; the bridge will automatically pick up the refreshed token on the next request.

### 3. Local API Key Authentication
The bridge protects all `/v1/*` endpoints with a persistent random token stored in `~/.agy-bridge/api_key` (permissions `0600`).
- **Automated client setups** (`agy-bridge setup-*`) read and inject this persistent key automatically.
- **Manual sessions or environment variables**: read the key directly with `cat ~/.agy-bridge/api_key`.

---

## Installation

### Option A: One-line install (Recommended)

Run directly in your terminal to install `agy-bridge` into `~/.local/bin` without manual Git cloning:

```bash
curl -fsSL https://raw.githubusercontent.com/albertopo94/agy-model-bridge/main/install.sh | bash
```

### Option B: Local development or pip

```bash
git clone https://github.com/albertopo94/agy-model-bridge.git
cd agy-model-bridge
pip install -e .
```

---

## Quick Start

### 1. Start the Bridge in the Background

```bash
agy-bridge start
```

This launches the gateway detached in the background, waits for health check confirmation, and automatically opens the local dashboard in your default web browser (`http://127.0.0.1:24980/`).

*Use `--no-open` to prevent opening the browser automatically, or `--port PORT` to customize the port.*

### 2. Configure Your Terminal Coding Agents

Configure your tools with a single command (with automated ISO backups and atomic file writes):

```bash
# Configure Claude Code CLI (~/.claude/settings.json)
agy-bridge setup-claude

# Configure Codex CLI (~/.codex/config.toml)
agy-bridge setup-codex
```

### 3. Manage the Background Service

```bash
# Check daemon status, active port, and discovered models
agy-bridge status

# Open or re-open the web dashboard at any time
agy-bridge dashboard

# Update agy-bridge in-place to the latest version (and auto-reload daemon)
agy-bridge update

# Check installed version
agy-bridge --version

# Stop the running background service
agy-bridge stop
```

---

## Client Integration

### 🎴 Claude Code CLI

Run the automated setup:
```bash
agy-bridge setup-claude
```
This automatically configures `~/.claude/settings.json` with:
- Model: `gemini-3.8-flash-high` (aliased to upstream `gemini-3.8-flash-tiered` with high thinking)
- Context window: 1,048,576 tokens (`CLAUDE_CODE_AUTO_COMPACT_WINDOW`)
- Gateway base URL: `http://127.0.0.1:24980`
- Curated `modelPicker` options for the `/model` slash command

Once configured, simply launch Claude:
```bash
claude
```

#### Changing Models in Claude Code (`/model`)
Typing `/model` inside Claude Code displays curated models ready to use:
1. **Gemini 3.8 Flash · High (AGY)** (`gemini-3.8-flash-high`) — *Default*
2. **Gemini 3.7 Flash · High (AGY)** (`gemini-3.7-flash-tiered`)
3. **Claude Sonnet 5.5 · High (AGY)** (`claude-sonnet-5-5-high`)
4. **Claude Sonnet 5.5 · Medium (AGY)** (`claude-sonnet-5-5-medium`)
5. **Claude Sonnet 5.5 · Low (AGY)** (`claude-sonnet-5-5-low`)
6. **Claude Opus 5.5 · High (AGY)** (`claude-opus-5-5-high`)
7. **Claude Opus 5.5 · Medium (AGY)** (`claude-opus-5-5-medium`)
8. **Claude Opus 5.5 · Low (AGY)** (`claude-opus-5-5-low`)
9. **Gemini 2.5 Pro (AGY)** (`gemini-2.5-pro`)
10. **Gemini 2.5 Flash (AGY)** (`gemini-2.5-flash`)

*(Alternative: set environment variables manually for a single session:)*
```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:24980" ANTHROPIC_AUTH_TOKEN="$(cat ~/.agy-bridge/api_key)" ANTHROPIC_MODEL="gemini-3.8-flash-high" CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1 && claude
```

### 🎴 Codex CLI

Run the automated setup:
```bash
agy-bridge setup-codex
```
This surgically adds an `[model_providers.agy]` block to `~/.codex/config.toml` using `wire_api = "responses"` and `model = "gemini-3.8-flash-high"`.

Once configured, launch Codex:
```bash
codex
```

### 🎴 Hermes Agent

Run the automated setup:
```bash
agy-bridge setup-hermes
```
This surgically configures `~/.hermes/config.yaml` with the local gateway endpoint and active API key.

*(Alternative: set environment variables manually for a single session:)*
```bash
export OPENAI_BASE_URL="http://127.0.0.1:24980/v1" OPENAI_API_KEY="$(cat ~/.agy-bridge/api_key)" && hermes
```

### 🎴 OpenCode

Run the automated setup:
```bash
agy-bridge setup-opencode
```
This surgically configures `~/.config/opencode/opencode.json` (or `opencode.jsonc`) with:
- Provider: `agy` configured with `@ai-sdk/openai-compatible`
- Model: `agy/gemini-3.8-flash-high`
- Gateway base URL: `http://127.0.0.1:24980/v1`

Once configured, launch OpenCode:
```bash
opencode
```

### 🎴 OpenClaw

Run the automated setup:
```bash
agy-bridge setup-openclaw
```
This surgically configures `~/.openclaw/openclaw.json` with:
- Provider: `agy` configured with OpenAI completions API
- Primary model: `agy/gemini-3.8-flash-high`
- Gateway base URL: `http://127.0.0.1:24980/v1`

Once configured, launch OpenClaw:
```bash
openclaw gateway
```

### 🎴 Cursor

Cursor routes AI requests through its cloud servers, so localhost requires an HTTPS tunnel (e.g. Cloudflare Tunnel, ngrok, or Tailscale) if Cursor cloud cannot reach localhost directly.

Run the setup guide:
```bash
agy-bridge setup-cursor
```
Follow the on-screen guide to:
1. Open Cursor **Settings** -> **Models** -> enable **Override OpenAI Base URL**.
2. Enter your bridge endpoint (e.g., `http://127.0.0.1:24980/v1` or public HTTPS tunnel URL).
3. Set API Key to your local key (read from `cat ~/.agy-bridge/api_key`).
4. Add models: `gemini-3.8-flash-high`, `claude-sonnet-5-5-high`, `claude-opus-5-5-high`, `gemini-2.5-pro`, `gemini-2.5-flash`.

### 🎴 Pi Coding Agent

Run the automated setup:
```bash
agy-bridge setup-pi
```
This surgically configures `~/.pi/agent/models.json` with:
- Provider: `agy` configured with OpenAI completions API
- Models: `gemini-3.8-flash-high`, `gemini-3.8`, `claude-sonnet-5-5-high/medium/low`, `claude-opus-5-5-high/medium/low`, `gemini-2.5-pro`, `gemini-2.5-flash`
- Base URL: `http://127.0.0.1:24980/v1`

Options:
- `--set-default`: Also sets `agy` and the default model as defaults in `~/.pi/agent/settings.json` (and synchronizes `enabledModels` if scoped).
- `--model <name>`: Specify a default model (default: `gemini-3.8-flash-high`).

Once configured, launch Pi or select an AGY model:
```bash
pi --model agy/gemini-3.8-flash-high
```
Or switch models inside Pi using `/model agy/gemini-3.8-flash-high`.

### 🎴 Gentle Shell

Run the automated setup:
```bash
agy-bridge setup-gentle-shell
```
This surgically configures `~/.gentle-shell/agent/models.json` with:
- Provider: `agy` configured with OpenAI completions API
- Models: `gemini-3.8-flash-high`, `gemini-3.8`, `claude-sonnet-5-5-high/medium/low`, `claude-opus-5-5-high/medium/low`, `gemini-2.5-pro`, `gemini-2.5-flash`
- Base URL: `http://127.0.0.1:24980/v1`

Options:
- `--set-default`: Also sets `agy` and the default model as defaults in `~/.gentle-shell/agent/settings.json`.
- `--model <name>`: Specify a default model (default: `gemini-3.8-flash-high`).

Once configured, launch Gentle Shell or select an AGY model:
```bash
gentle-shell --model agy/gemini-3.8-flash-high
```
Or switch models inside Gentle Shell using `/model agy/gemini-3.8-flash-high`.

### 🎴 FreeLLMAPI
Register this bridge as an OpenAI-compatible Custom Provider in FreeLLMAPI:
- **Base URL**: `http://127.0.0.1:24980/v1`
- **API Key**: Your local key (from `cat ~/.agy-bridge/api_key`)

---

## Restoring Configuration Backups

Before modifying any configuration files, `agy-bridge` creates timestamped backups. You can restore previous configurations at any time with automated provenance detection:

```bash
# Restore Claude Code configuration
agy-bridge restore-claude

# Restore Codex CLI configuration
agy-bridge restore-codex

# Restore OpenCode configuration
agy-bridge restore-opencode

# Restore OpenClaw configuration
agy-bridge restore-openclaw

# Restore Pi Coding Agent configuration
agy-bridge restore-pi

# Restore Gentle Shell configuration
agy-bridge restore-gentle-shell
```

The interactive selector classifies each backup so you know exactly what you are restoring:
```text
Backups disponibles para Claude Code:
  [1] settings.json.backup-2026-09-30T14-07-08  [AGY Bridge]  <-- Anterior inmediata
  [2] settings.json.backup-2026-09-30T13-43-12  [FreeLLMAPI]
  [3] settings.json.backup-2026-09-22T17-00-18-257Z  [Anthropic Original]

Ingrese un número (1-3), presione Enter para [1], o 'q' para cancelar:
```

*Use `--latest` to restore the immediate previous backup directly without interactive prompts.*

---

## Uninstallation

To completely uninstall AGY Model Bridge, stop the running background daemon, remove the CLI binaries and daemon directory (`~/.agy-bridge`), and restore Claude Code, Codex CLI, OpenCode, OpenClaw, Pi, and Gentle Shell configurations to their original state:

### Option A: Via the installed CLI

```bash
agy-bridge uninstall
```

Options:
- `-y`, `--yes`: Skip interactive confirmation prompt.
- `--purge`: Purge all historical configuration backups.
- `--keep-configs`: Keep current configurations without restoring client configs.

### Option B: One-line uninstaller (Remote / Script)

```bash
curl -fsSL https://raw.githubusercontent.com/albertopo94/agy-model-bridge/main/uninstall.sh | bash
```

---

## CLI Command Reference

| Command | Description |
|---|---|
| `agy-bridge start` | Starts background daemon and opens web dashboard automatically |
| `agy-bridge stop` | Stops the running background daemon |
| `agy-bridge status` | Checks daemon status, port, models count, and auth |
| `agy-bridge dashboard` (or `open`) | Opens the local dashboard in your default browser |
| `agy-bridge update` (or `upgrade`) | Updates installation in-place via git pull and reloads daemon |
| `agy-bridge --version` (or `-v`) | Prints the bridge version |
| `agy-bridge setup-claude` | Surgically configures Claude Code (`~/.claude/settings.json`) |
| `agy-bridge restore-claude` | Interactively restores a Claude Code configuration backup |
| `agy-bridge setup-codex` | Surgically configures Codex CLI (`~/.codex/config.toml`) |
| `agy-bridge restore-codex` | Interactively restores a Codex CLI configuration backup |
| `agy-bridge setup-opencode` | Surgically configures OpenCode (`~/.config/opencode/opencode.json`) |
| `agy-bridge restore-opencode` | Interactively restores an OpenCode configuration backup |
| `agy-bridge setup-openclaw` | Surgically configures OpenClaw (`~/.openclaw/openclaw.json`) |
| `agy-bridge restore-openclaw` | Interactively restores an OpenClaw configuration backup |
| `agy-bridge setup-cursor` | Setup guide for Cursor AI editor |
| `agy-bridge setup-pi` | Surgically configures Pi Coding Agent (`~/.pi/agent/models.json`) |
| `agy-bridge restore-pi` | Interactively restores a Pi configuration backup |
| `agy-bridge setup-gentle-shell` | Surgically configures Gentle Shell (`~/.gentle-shell/agent/models.json`) |
| `agy-bridge restore-gentle-shell` | Interactively restores a Gentle Shell configuration backup |
| `agy-bridge setup-hermes` | Surgically configures Hermes Agent (`~/.hermes/config.yaml`) |
| `agy-bridge restore-hermes` | Interactively restores a Hermes Agent configuration backup |
| `agy-bridge uninstall` | Uninstalls bridge, terminates daemon, and restores client configs |

---

## Running Tests

### Unit and Integration Tests

Execute the complete test suite:

```bash
python3 -m unittest discover -s tests -v
```

All 871 tests run in ~3-4 seconds locally with zero external dependencies and zero network access.

### End-to-End Smoke Test

Run the 9-stage live verification script against a running bridge server:

```bash
python3 scripts/smoke_test.py --host 127.0.0.1 --port 24980
```

