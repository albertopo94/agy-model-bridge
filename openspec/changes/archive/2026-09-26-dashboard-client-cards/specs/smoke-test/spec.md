# Delta for Smoke Test

## MODIFIED Requirements

### Requirement: Comprehensive Endpoint Verification

The script MUST sequentially verify all supported bridge endpoints:
1. `GET /healthz` returns HTTP 200 with `status == "ok"`.
2. `GET /v1/models` returns HTTP 200 with non-empty `data` list.
3. `GET /` returns HTTP 200 with `Content-Type: text/html` and contains:
   - All 4 client cards: "Claude Code", "Codex CLI", "Hermes Agent", and "FreeLLMAPI".
   - Both "Configuración automática" and "Conexión manual" sections with copy triggers.
   - Correct endpoint URLs (`http://127.0.0.1:<port>` for Claude Code, `http://127.0.0.1:<port>/v1` for OpenAI-compatible clients).
   - "Documentación" external reference links.
4. `POST /v1/chat/completions` with `stream: false` returns non-empty message content.
5. `POST /v1/chat/completions` with `stream: true` receives SSE chunk events terminating in `[DONE]`.
6. `POST /v1/messages` with `stream: false` returns valid Anthropic message schema with non-empty text content.
7. `POST /v1/messages` with `stream: true` receives Anthropic SSE events terminating in `message_stop`.
8. `POST /v1/responses` with `stream: false` returns valid OpenAI Response schema with non-empty output text.
9. `POST /v1/responses` with `stream: true` receives OpenAI Responses SSE events terminating in `response.completed`.

The script MUST assert non-empty response content, valid protocol structures, and four-card dashboard contents across all verification stages.
(Previously: Verified 3 generic cards on GET / without asserting two-tier sections or all 4 dedicated cards)

#### Scenario: All endpoints succeed
- GIVEN a fully operational bridge server connected to upstream Cloud Code Assist
- WHEN `scripts/smoke_test.py` executes all test cases
- THEN each test case passes assertion including all 4 client cards in GET /
- AND the script prints diagnostic progress for each stage
- AND exits with status code 0.

#### Scenario: Dashboard cards verification failure
- GIVEN the dashboard HTML is missing any of the 4 client cards or their two-tier sections
- WHEN `scripts/smoke_test.py` runs
- THEN the script pinpoints the missing card or section in stage [3/9]
- AND terminates immediately with exit code 1.
