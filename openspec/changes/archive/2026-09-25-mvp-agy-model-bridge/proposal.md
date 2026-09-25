# Proposal: MVP Antigravity Model Bridge

## Intent

Enable OpenAI-compatible clients to route generation requests through Google Cloud Code Assist (`daily-cloudcode-pa.googleapis.com`) using macOS Keychain credentials, with zero external Python dependencies.

## Scope

### In Scope
- Extract active access tokens from macOS Keychain (`gemini/antigravity` via `security find-generic-password`) with in-memory TTL caching and auto re-read on HTTP 401.
- Discover upstream active project (`loadCodeAssist`) and models (`fetchAvailableModels`).
- Serve OpenAI-compatible endpoints via `http.server.ThreadingHTTPServer`: `GET /healthz`, `GET /v1/models`, and `POST /v1/chat/completions` (JSON and real-time SSE streaming).
- Bidirectional conversion between OpenAI format and Cloud Code Assist `contents`/`parts`, filtering upstream reasoning/thought blocks from output deltas.
- Zero-dependency implementation using Python 3 standard library (`http.server`, `urllib.request`, `subprocess`, `json`, `base64`).
- Comprehensive unit test suite with `python3 -m unittest` following strict TDD.
- Live smoke test script verifying endpoint contracts.

### Out of Scope
- Function/tool calling (deferred to post-MVP).
- OAuth token refresh exchange (relies on active Keychain token).
- FreeLLMAPI configuration integration.

## Capabilities

### New Capabilities
- `keychain-auth`: Extract, cache, and parse active access token from macOS Keychain with proactive 401 retry.
- `cloudcode-client`: Upstream HTTP client for loadCodeAssist, fetchAvailableModels, and streamGenerateContent.
- `openai-adapter`: Concurrent OpenAI-compatible HTTP server translating chat completions to/from upstream format with SSE thought filtering.
- `smoke-test`: Test harness verifying bridge against live Keychain & endpoints.

### Modified Capabilities
None

## Approach

1. Build modular core in `bridge/` using standard library exclusively (`auth`, `client`, `transform`, `server`).
2. Implement `keychain-auth` with in-memory TTL cache (60s buffer) and immediate Keychain re-read on upstream 401.
3. Implement `cloudcode-client` via `urllib.request` supporting SSE chunk streaming and upstream error mapping.
4. Implement `openai-adapter` using `http.server.ThreadingHTTPServer` with line-buffered SSE chunk streaming and `thought: true` filtering.
5. Apply strict TDD (Red-Green-Refactor) for all transform and server units.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `bridge/` | New | Core bridge modules (auth, client, adapter, transforms) |
| `scripts/smoke_test.py` | New | Live endpoint verification script |
| `tests/` | New | Standard library unit test suite |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Expired Keychain token | Medium | In-memory cache invalidation + single Keychain re-read retry; diagnostic 401 if still failing |
| Upstream API drift | Low | Contract unit tests and runnable smoke verification |
| SSE thought metadata noise | Medium | Explicitly filter non-content/thought blocks in transform layer |
| SSE stream latency | Low | Line-buffered flush chunks immediately without accumulation |

## Rollback Plan

Delete created `bridge/`, `tests/`, `scripts/`, and `openspec/changes/mvp-agy-model-bridge/` directories, restoring initial state.

## Dependencies

- macOS environment with `security` CLI and populated `gemini/antigravity` Keychain entry.
- Python 3.10+ standard library.

## Success Criteria

- [ ] `python3 -m unittest` passes 100% without external dependencies.
- [ ] `GET /healthz` returns `{"status": "ok"}`.
- [ ] `GET /v1/models` returns model list fetched from upstream.
- [ ] `POST /v1/chat/completions` responds accurately in non-stream and stream modes.
- [ ] `scripts/smoke_test.py` executes successfully against live upstream.
