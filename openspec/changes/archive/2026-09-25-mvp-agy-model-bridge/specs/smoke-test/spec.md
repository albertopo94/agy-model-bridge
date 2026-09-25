# Smoke Test Specification

## Purpose

Provide a standalone, zero-dependency verification script to validate bridge server operation against live upstream endpoints.

## Requirements

### Requirement: Standalone Script Execution

The smoke test SHALL be located at `scripts/smoke_test.py` and MUST execute using Python 3 standard library only (`urllib.request`, `json`, `sys`, `argparse`). It SHOULD accept `--host` (default `127.0.0.1`) and `--port` (default `8080`) arguments.

#### Scenario: Script runs with default parameters
- GIVEN a running bridge server on `127.0.0.1:8080`
- WHEN `python3 scripts/smoke_test.py` is executed
- THEN the script connects to the default host and port without errors.

### Requirement: Comprehensive Endpoint Verification

The script MUST sequentially verify:
1. `GET /healthz` returns HTTP 200 with `status == "ok"`.
2. `GET /v1/models` returns HTTP 200 with non-empty `data` list.
3. `POST /v1/chat/completions` with `stream: false` returns non-empty message content.
4. `POST /v1/chat/completions` with `stream: true` receives SSE chunk events terminating in `[DONE]`.

The script MUST assert non-empty response content on each completion test.

#### Scenario: All endpoints succeed
- GIVEN a fully operational bridge server connected to upstream Cloud Code Assist
- WHEN `scripts/smoke_test.py` executes all test cases
- THEN each test case passes assertion
- AND the script prints diagnostic progress for each stage
- AND exits with status code 0.

### Requirement: Diagnostic Failure and Non-Zero Exit Code

If any endpoint returns an error status code, fails assertion, or times out, the script MUST output a clear diagnostic message indicating the failing stage and details, and MUST exit immediately with exit code 1.

#### Scenario: Endpoint failure produces exit code 1
- GIVEN the bridge server is unreachable or an endpoint fails an assertion
- WHEN `scripts/smoke_test.py` runs
- THEN the script prints the specific failure description
- AND terminates with exit code 1.
