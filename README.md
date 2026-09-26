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
  - `POST /v1/messages` — Anthropic Messages API shim with SSE stream mapping (`message_start`, `content_block_delta`, `message_delta`, `message_stop`) for Claude Code CLI.
- **macOS Keychain OAuth Integration**: Seamlessly extracts Google OAuth credentials stored by Antigravity in Keychain (`service="gemini"`, `account="antigravity"`) with thread-safe TTL caching and automatic 401 re-read.
- **Adaptive Thinking Configuration**: Intelligently configures `thinkingConfig` for Gemini reasoning models while strictly omitting it when budget is 0 or disabled, preventing protobuf validation errors.

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

## Quick Start

### 1. Start the Bridge Server

```bash
python3 -m bridge --host 127.0.0.1 --port 8080
```

CLI options:
- `--host`: Host address to bind (default: `127.0.0.1`).
- `--port`: Port number to bind (default: `8080`).
- `--project`: Optional Google Cloud project ID override (defaults to auto-discovery via `loadCodeAssist`).
- `--base-url`: Optional upstream API base URL override.

### 2. Open the Local Dashboard

Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/) in your browser to view active status badges, discovered models, and one-click copyable setup cards for each tool.

---

## Client Integration

### 🎴 Claude Code CLI
Claude Code expects the Anthropic Messages protocol and custom base URL without `/v1`:

```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:8080" ANTHROPIC_AUTH_TOKEN="local-bridge" ANTHROPIC_CUSTOM_MODEL_OPTION="gemini-2.5-flash" CLAUDE_CODE_USE_GATEWAY=1 && claude
```

### 🎴 Codex CLI
Add the custom model provider block to `~/.codex/config.toml`:

```toml
[model]
wire_api = "responses"
base_url = "http://127.0.0.1:8080/v1"
```

Or append it in one line:
```bash
mkdir -p ~/.codex && printf '\n[model]\nwire_api = "responses"\nbase_url = "http://127.0.0.1:8080/v1"\n' >> ~/.codex/config.toml
```

### 🎴 Hermes Agent
Hermes Agent connects using standard OpenAI environment variables:

```bash
export OPENAI_BASE_URL="http://127.0.0.1:8080/v1" OPENAI_API_KEY="local-bridge" && hermes
```

### 🎴 FreeLLMAPI
Register this bridge as an OpenAI-compatible Custom Provider:
- **Base URL**: `http://127.0.0.1:8080/v1`
- **API Key**: `local-bridge` (or any string)

---

## Running Tests

### Unit and Integration Tests

Execute the complete test suite:

```bash
python3 -m unittest discover -s tests -v
```

All 223 tests run in ~1 second with zero external dependencies and zero network access.

### End-to-End Smoke Test

Run the 9-stage live verification script against a running bridge server:

```bash
python3 scripts/smoke_test.py --host 127.0.0.1 --port 8080
```
