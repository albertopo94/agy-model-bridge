# AGY Model Bridge

Zero-dependency, pure Python 3 local AI gateway that bridges the Google Cloud Code Assist backend (`daily-cloudcode-pa.googleapis.com`) to standard client protocols, providing native model access for **Claude Code**, **Codex CLI**, **Hermes Agent**, and **FreeLLMAPI**.

---

## Features

- **Zero External Dependencies**: Built entirely using the Python 3 standard library (`http.server`, `urllib.request`, `subprocess`, `json`, `base64`, `threading`, `time`). No `pip install`, no virtual environment, no Node.js required.
- **Multi-Protocol Gateway**:
  - `GET /` — Self-contained dark-mode dashboard (Geist/Vercel styling) with live Keychain auth badges, model count, and one-click copyable setup cards.
  - `GET /v1/models` — Dynamic model catalog discovered directly from upstream Cloud Code Assist with Codex serde compatibility (`data`, `models`, `slug`, `display_name`).
  - `POST /v1/chat/completions` — OpenAI Chat Completions API with full streaming (SSE `text/event-stream`) and non-streaming support (for FreeLLMAPI, Hermes Agent, Aider).
  - `POST /v1/responses` — OpenAI Responses API shim for Codex CLI (`wire_api = "responses"`).
  - `POST /v1/messages` — Anthropic Messages API shim with dynamic SSE stream mapping (`thinking_delta`, `text_delta`, `tool_use`, `input_json_delta`), recursive OpenAPI 3.0 schema sanitization, and full tool calling for Claude Code CLI.
- **Built-in Setup CLI**: Native subcommands (`setup-claude`, `setup-codex`) that surgically configure client environments with atomic writes, file permissions `0o600`, and automatic timestamped backups.
- **macOS Keychain OAuth Integration**: Seamlessly extracts Google OAuth credentials stored by Antigravity in Keychain (`service="gemini"`, `account="antigravity"`) with thread-safe TTL caching and automatic 401 re-read.
- **Adaptive Thinking & Model Aliasing**: Intelligently resolves `gemini-3.8-flash-high` / `auto` to upstream `gemini-3.8-flash-tiered`, automatically configuring reasoning levels (`HIGH`, `MEDIUM`, `LOW`) and token budgets.

---

## Requirements

- **Operating System**: macOS (Apple Silicon or Intel)
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

Once configured, simply launch Claude:
```bash
claude
```

*(Alternative: set environment variables manually for a single session:)*
```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:24980" ANTHROPIC_AUTH_TOKEN="antigravity" ANTHROPIC_MODEL="gemini-3.8-flash-high" CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1 && claude
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
Hermes Agent connects using standard OpenAI environment variables:

```bash
export OPENAI_BASE_URL="http://127.0.0.1:24980/v1" OPENAI_API_KEY="local-bridge" && hermes
```

### 🎴 FreeLLMAPI
Register this bridge as an OpenAI-compatible Custom Provider in FreeLLMAPI:
- **Base URL**: `http://127.0.0.1:24980/v1`
- **API Key**: `local-bridge` (or any string)

---

## Running Tests

### Unit and Integration Tests

Execute the complete test suite:

```bash
python3 -m unittest discover -s tests -v
```

All 291 tests run in ~1 second with zero external dependencies and zero network access.

### End-to-End Smoke Test

Run the 9-stage live verification script against a running bridge server:

```bash
python3 scripts/smoke_test.py --host 127.0.0.1 --port 24980
```
