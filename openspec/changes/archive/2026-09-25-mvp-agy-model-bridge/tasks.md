# Tasks: MVP Antigravity Model Bridge

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 900–1200 lines |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (Transforms) → PR 2 (Auth & Client) → PR 3 (Server & E2E) |
| Delivery strategy | size-exception |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No (maintainer accepted size:exception)
Chain strategy: size-exception
400-line budget risk: High (waived via size:exception)

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Core pure transforms & tests | PR 1 | Base: `main` (or tracker); pure conversion logic |
| 2 | Keychain auth & upstream client | PR 2 | Base: PR 1; transport & credential adapters |
| 3 | HTTP server, CLI & smoke test | PR 3 | Base: PR 2; request handling & e2e verification |

## Phase 1: Core Pure Transforms

- [x] 1.1 [RED] Create `tests/test_transform.py` testing role translation, SSE event parsing, thought filtering, chunk building, and error responses.
- [x] 1.2 [GREEN] Implement `bridge/__init__.py` and `bridge/transform.py` with pure conversion logic to satisfy all transform tests.
- [x] 1.3 [REFACTOR] Clean up transform helpers and verify test suite passes via `python3 -m unittest tests.test_transform`.

## Phase 2: Keychain Auth & Token Cache

- [x] 2.1 [RED] Create `tests/test_auth.py` testing Keychain CLI extraction, base64 decoding, 60s TTL caching, and 401 invalidation.
- [x] 2.2 [GREEN] Implement `bridge/auth.py` with `KeychainTokenProvider` and thread-safe TTL cache to pass tests.
- [x] 2.3 [REFACTOR] Streamline cache locking and verify test suite passes via `python3 -m unittest tests.test_auth`.

## Phase 3: CloudCode Upstream Client

- [x] 3.1 [RED] Create `tests/test_client.py` testing request headers, discovery APIs, SSE line generator, typed errors, and 401 retry.
- [x] 3.2 [GREEN] Implement `bridge/client.py` with `CloudCodeClient` using `urllib.request` to satisfy all client tests.
- [x] 3.3 [REFACTOR] Refactor response decoding helpers and verify test suite passes via `python3 -m unittest tests.test_client`.

## Phase 4: HTTP Server & Endpoints

- [x] 4.1 [RED] Create `tests/test_server.py` testing `/healthz`, `/v1/models`, streaming/non-streaming `/v1/chat/completions`, and error mappings.
- [x] 4.2 [GREEN] Implement `bridge/server.py` (`ThreadingHTTPServer`) and `bridge/__main__.py` CLI runner to pass tests.
- [x] 4.3 [REFACTOR] Polish request routing and verify test suite passes via `python3 -m unittest tests.test_server`.

## Phase 5: Verification & Smoke Test

- [x] 5.1 Implement `scripts/smoke_test.py` validating health, models, and completions with non-zero exit codes on failure.
- [x] 5.2 Execute full test suite `python3 -m unittest discover tests` and verify 100% pass without external dependencies.
