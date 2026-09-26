# Tasks: Local Gateway Dashboard & Protocol Shims

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | ~1100-1400 lines |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (Phases 1-2) → PR 2 (Phase 3) → PR 3 (Phases 4-6) |
| Delivery strategy | ask-on-risk |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: size-exception
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|---|---|---|---|
| 1 | Thinking heuristics & gateway dashboard | PR 1 | Base: `main`; delivers Phases 1-2 |
| 2 | Anthropic Messages shim | PR 2 | Base: PR 1; Claude Code support (Phase 3) |
| 3 | Responses shim, server dispatch & smoke tests | PR 3 | Base: PR 2; Codex support & smoke tests (Phases 4-6) |

## Phase 1: Adaptive Thinking Configuration

- [x] 1.1 [RED] Add unit tests in `tests/test_transform.py` asserting `build_thinking_config()` for `-high`, `-medium`, `-low`, standard models (`thinkingBudget: 0`), and payload overrides.
- [x] 1.2 [GREEN] Implement `build_thinking_config()` in `bridge/transform.py` and wire into `openai_to_cloudcode_request()`.
- [x] 1.3 [REFACTOR] Clean up model suffix heuristics and typing in `bridge/transform.py`.

## Phase 2: Embedded Dark-Mode Dashboard

- [x] 2.1 [RED] Add unit tests in `tests/test_dashboard.py` asserting HTML markup, styling, status badges, setup cards, and `get_status_data()`.
- [x] 2.2 [GREEN] Implement `render_dashboard()` and `get_status_data()` in `bridge/dashboard.py` using standard library only.
- [x] 2.3 [REFACTOR] Polish dashboard inline CSS and zero-dependency clipboard JS in `bridge/dashboard.py`.

## Phase 3: Anthropic Messages API Shim

- [x] 3.1 [RED] Add unit tests in `tests/test_anthropic.py` asserting request translation, non-streaming response JSON, and strict SSE event sequence.
- [x] 3.2 [GREEN] Implement `bridge/anthropic.py` with `anthropic_to_cloudcode_request()`, response builder, and `build_anthropic_sse_events()`.
- [x] 3.3 [REFACTOR] Refactor SSE event generators and Anthropic error mapping in `bridge/anthropic.py`.

## Phase 4: OpenAI Responses API Shim

- [x] 4.1 [RED] Add unit tests in `tests/test_responses.py` asserting input item extraction, non-streaming completion, and Responses SSE event sequence.
- [x] 4.2 [GREEN] Implement `bridge/responses.py` with `responses_to_cloudcode_request()`, response builder, and `build_responses_sse_events()`.
- [x] 4.3 [REFACTOR] Standardize response item formatting and error schema handling in `bridge/responses.py`.

## Phase 5: Gateway Server Multi-Protocol Dispatching

- [x] 5.1 [RED] Add integration tests in `tests/test_server.py` verifying routes for `/`, `/api/status`, `/v1/messages`, and `/v1/responses`.
- [x] 5.2 [GREEN] Update `OpenAIRequestHandler` in `bridge/server.py` to route multi-protocol endpoints to their respective handlers.
- [x] 5.3 [REFACTOR] Consolidate HTTP streaming and error responses in `bridge/server.py` across protocols.

## Phase 6: Multi-Protocol Smoke Test & Verification

- [x] 6.1 Update `scripts/smoke_test.py` to verify all 9 endpoints including dashboard, Anthropic, and Responses.
- [x] 6.2 Run full test suite with `python3 -m unittest` and confirm 100% pass across all test modules.
