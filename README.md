# AGY Model Bridge

Zero-dependency, pure Python 3 HTTP service that bridges Google Cloud Code Assist backend (`daily-cloudcode-pa.googleapis.com`) to an OpenAI-compatible REST API (`/healthz`, `/v1/models`, `/v1/chat/completions`).

## Features

- **Zero External Dependencies**: Built entirely using Python 3 standard library (`http.server`, `urllib.request`, `subprocess`, `json`, `base64`, `threading`, `time`).
- **macOS Keychain OAuth Integration**: Seamlessly extracts Google OAuth credentials stored by Antigravity CLI in Keychain (`service="gemini"`, `account="antigravity"`) with thread-safe TTL caching and automatic 401 re-authentication.
- **OpenAI-Compatible Endpoints**:
  - `GET /healthz` - Health check.
  - `GET /v1/models` - Catalog of models retrieved dynamically from Google Cloud Code Assist.
  - `POST /v1/chat/completions` - Supports both streaming (SSE `text/event-stream`) and non-streaming responses.
- **Protobuf & API Normalization**:
  - Handles Cloud Code's required request wrapping (`"request": {"contents": [...]}`).
  - Unwraps SSE responses (`{"response": {"candidates": [...]}}`).
  - Filters model thought blocks (`"thought": true`).
  - Normalizes message roles, turn alternation, and generation configs.

## Requirements

- macOS with Antigravity CLI installed and logged in (`agy login`).
- Python 3.10+

## Quick Start

### 1. Start the Bridge Server

```bash
python3 -m bridge --host 127.0.0.1 --port 8080
```

CLI options:
- `--host`: Host address to bind (default: `127.0.0.1`).
- `--port`: Port number to bind (default: `8080`).
- `--project`: Optional Google Cloud project ID override.
- `--base-url`: Optional upstream API base URL override.

### 2. Verify with Smoke Test

In another terminal, run the automated smoke test suite:

```bash
python3 scripts/smoke_test.py --host 127.0.0.1 --port 8080
```

You can optionally target a specific model:

```bash
python3 scripts/smoke_test.py --host 127.0.0.1 --port 8080 --model gemini-2.5-flash
```

## Running Tests

Execute the unit test suite:

```bash
python3 -m unittest discover -s tests -v
```

All 146 unit tests run in less than 1 second without network access.
