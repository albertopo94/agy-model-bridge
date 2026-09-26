# Delta for Smoke Test

## MODIFIED Requirements

### Requirement: Comprehensive Endpoint Verification

The script MUST sequentially verify all supported bridge endpoints:
1. `GET /healthz` returns HTTP 200 with `status == "ok"`.
2. `GET /v1/models` returns HTTP 200 with non-empty `data` list.
3. `GET /` returns HTTP 200 with `Content-Type: text/html` and contains dashboard structure (badges, cards).
4. `POST /v1/chat/completions` with `stream: false` returns non-empty message content.
5. `POST /v1/chat/completions` with `stream: true` receives SSE chunk events terminating in `[DONE]`.
6. `POST /v1/messages` with `stream: false` returns valid Anthropic message schema with non-empty text content.
7. `POST /v1/messages` with `stream: true` receives Anthropic SSE events terminating in `message_stop`.
8. `POST /v1/responses` with `stream: false` returns valid OpenAI Response schema with non-empty output text.
9. `POST /v1/responses` with `stream: true` receives OpenAI Responses SSE events terminating in `response.completed`.

The script MUST assert non-empty response content and valid protocol structures across all verification stages.
(Previously: Verified only /healthz, /v1/models, and OpenAI /v1/chat/completions non-streaming and streaming)

#### Scenario: All endpoints succeed
- GIVEN a fully operational bridge server connected to upstream Cloud Code Assist
- WHEN `scripts/smoke_test.py` executes all test cases
- THEN each test case passes assertion
- AND the script prints diagnostic progress for each stage
- AND exits with status code 0.

#### Scenario: Multi-protocol verification failure
- GIVEN any endpoint (`/`, `/v1/messages`, or `/v1/responses`) returns an invalid status, malformed event, or empty content
- WHEN `scripts/smoke_test.py` runs
- THEN the script prints a descriptive diagnostic message identifying the failed protocol stage
- AND terminates immediately with exit code 1.
