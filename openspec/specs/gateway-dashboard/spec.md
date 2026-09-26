# Gateway Dashboard Specification

## Purpose

Serve a self-contained, zero-dependency dark-mode dashboard at the HTTP root (`GET /`) displaying real-time bridge status badges and interactive copyable client setup snippets for FreeLLMAPI, Claude Code, and Codex/Hermes/Aider.

## Requirements

### Requirement: Dark-Mode Dashboard Endpoint

The server MUST handle `GET /` and return HTTP 200 with `Content-Type: text/html; charset=utf-8`.
The HTML document MUST be self-contained with embedded CSS and JavaScript, requiring zero external CDN requests, fonts, or libraries.
The UI SHALL render in a dark-mode palette (`#0f172a` slate background, `#1e293b` container cards, `#38bdf8` accent highlights, and monospace code blocks).

#### Scenario: Access root dashboard successfully
- GIVEN the bridge server is active on `127.0.0.1:8080`
- WHEN a user or browser sends `GET /`
- THEN the server returns HTTP 200 with `Content-Type: text/html; charset=utf-8`
- AND the body contains self-contained HTML with styling and interaction scripts.

#### Scenario: Non-GET method on root path
- GIVEN a client sends `POST /`, `PUT /`, or `DELETE /`
- WHEN the request reaches the server
- THEN the server returns HTTP 404 or HTTP 405 error schema.

### Requirement: Real-Time Bridge Status Badges

The dashboard MUST render three live status badges:
1. **Keychain Auth**: SHALL indicate token status (`Valid`, `Expired`, or `Missing`) with connected account info. If invalid or expired, it MUST display an actionable resolution prompt (`Open Antigravity to refresh`).
2. **Discovered Models**: SHALL display the integer count of available upstream models discovered via Cloud Code Assist.
3. **Active Port & Host**: SHALL display the listening address (e.g., `127.0.0.1:8080`).

#### Scenario: Display healthy status badges
- GIVEN a valid Keychain token and 27 discovered upstream models
- WHEN `GET /` is loaded
- THEN the dashboard displays active badges for Keychain auth (`Valid`), model count (`27 Models Discovered`), and active address (`127.0.0.1:8080`).

#### Scenario: Display degraded auth badge with actionable guidance
- GIVEN Keychain token is missing or expired
- WHEN `GET /` is loaded
- THEN the Keychain badge displays warning/error state
- AND displays clear instructions directing the user to open Antigravity to refresh credentials.

### Requirement: Interactive Client Configuration Cards

The dashboard MUST display three interactive client configuration cards, each featuring a click-to-copy code snippet:
1. **Card 1 (FreeLLMAPI Bridge)**: OpenAI-compatible endpoint URL (`http://127.0.0.1:<port>/v1`), bearer token instructions, and custom provider setup snippet.
2. **Card 2 (Claude Code Direct)**: Base URL without `/v1` (`http://127.0.0.1:<port>`), environment variable exports (`export ANTHROPIC_BASE_URL=...`, `export ANTHROPIC_AUTH_TOKEN=...`), and direct CLI invocation command.
3. **Card 3 (Codex / Hermes / Aider Direct)**: Base URL with `/v1` (`http://127.0.0.1:<port>/v1`), Codex `~/.codex/config.toml` block with `wire_api = "responses"`, and Hermes/Aider chat completions configuration snippet.

Embedded JavaScript MUST provide one-click clipboard copying with visual confirmation feedback.

#### Scenario: Copy client configuration snippet
- GIVEN the dashboard rendered in a browser
- WHEN a user clicks the copy button on the Claude Code card
- THEN the exact configuration command is written to the system clipboard
- AND the button displays temporary visual confirmation.

#### Scenario: Clipboard copy failure fallback
- GIVEN clipboard API is unavailable or restricted by browser permissions
- WHEN a user clicks the copy button
- THEN the snippet textarea remains selectable for manual copying without throwing unhandled exceptions.
