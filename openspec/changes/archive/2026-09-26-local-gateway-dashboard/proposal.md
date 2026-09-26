# Proposal: Local Gateway Dashboard & Protocol Shims

## Intent

Transform `agy-model-bridge` into a multi-client gateway with a zero-dependency local dashboard, protocol shims for Claude Code and Codex CLI, and adaptive thinking configuration to eliminate Gemini token starvation.

## Scope

### In Scope
- Dark-mode dashboard at `GET /` with status badges and client config cards.
- Anthropic Messages shim (`POST /v1/messages`) for Claude Code CLI.
- OpenAI Responses shim (`POST /v1/responses`) for Codex CLI.
- Adaptive `thinkingConfig` for Gemini models.
- Smoke test updates covering all routes.

### Out of Scope
- External UI frameworks or npm packages.
- Standalone OAuth refresh without Antigravity.
- Multi-process daemon architecture.

## Capabilities

### New Capabilities
- `gateway-dashboard`: Embedded dark-mode UI at `GET /` with status badges and setup cards.
- `anthropic-shim`: Anthropic Messages API (`POST /v1/messages`) for Claude Code CLI.
- `responses-shim`: OpenAI Responses API (`POST /v1/responses`) for Codex CLI.

### Modified Capabilities
- `openai-adapter`: Multi-protocol dispatching and adaptive thinking config.
- `smoke-test`: Verification of dashboard, Messages, and Responses shims.

## Approach

- **Dashboard**: Inline HTML/CSS/JS served via `http.server` polling status endpoints.
- **Protocol Shims**: Dedicated transformers mapping Anthropic and Responses schemas to Cloud Code.
- **Adaptive Thinking**: Detect Gemini reasoning variants (`-high`, `-low`, `-medium`) to configure `thinkingConfig`.
- **Architecture**: Single unified daemon sharing token cache and HTTP client.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `bridge/server.py` | Modified | Routes for `/`, `/v1/messages`, `/v1/responses` |
| `bridge/transform.py` | Modified | Adaptive `thinkingConfig` generation |
| `bridge/dashboard.py` | New | Embedded HTML/CSS/JS dashboard |
| `bridge/anthropic.py` | New | Anthropic Messages translation layer |
| `bridge/responses.py` | New | OpenAI Responses translation layer |
| `scripts/smoke_test.py` | Modified | Multi-protocol verification |
| `tests/` | Modified | Unit tests for dashboard and shims |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Thinking starvation | Medium | Set adaptive budget defaults with client overrides |
| SSE mismatch | Medium | Validate exact Anthropic and OpenAI event specs |
| Token expiry without AGY | Low | Dashboard status badge with actionable errors |

## Rollback Plan

Revert git commit. All new routes are additive; `/v1/chat/completions` remains unchanged.

## Dependencies

- Python 3 standard library only.
- Active Antigravity session with Keychain credentials.

## Success Criteria

- [ ] `GET /` serves dark-mode dashboard with live status badges.
- [ ] `POST /v1/messages` handles Claude Code CLI requests.
- [ ] `POST /v1/responses` handles Codex CLI requests.
- [ ] Gemini thinking models output full content without empty responses.
- [ ] `python3 -m unittest` passes cleanly.
- [ ] `python3 scripts/smoke_test.py` validates all endpoints.
