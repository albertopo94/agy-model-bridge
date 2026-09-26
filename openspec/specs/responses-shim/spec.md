# Responses Shim Specification

## Purpose

Expose an OpenAI Responses API (`POST /v1/responses`) translating OpenAI Responses request payloads and Server-Sent Events to and from Google Cloud Code Assist format for Codex CLI (`wire_api = "responses"`) and compatible clients.

## Requirements

### Requirement: Responses Request Validation and Translation

The server MUST accept `POST /v1/responses` with JSON payload containing:
- `model`: required string identifying the model.
- `input`: required list of input items or strings representing conversation history.
- `instructions`: optional string providing system/developer guidance.
- `stream`: optional boolean (default `false`).

The transform layer MUST translate the payload into Cloud Code Assist parameters:
- `instructions` mapped to `systemInstruction.parts[].text`.
- `input` parsed and mapped to `contents`:
  - Items with `role: "user"` or string inputs mapped to role `user`.
  - Items with `role: "assistant"` mapped to role `model`.
  - Sub-blocks of type `input_text` extracted into turn text parts.
- Alternation and turn order rules MUST be enforced.
- Configures adaptive thinking according to model capabilities.

#### Scenario: Translate valid Codex Responses request
- GIVEN a `POST /v1/responses` request with `instructions`, `input` items, and target `model`
- WHEN the shim processes the request
- THEN it creates valid Cloud Code `systemInstruction` and `contents` structures
- AND passes them to the upstream client.

#### Scenario: Reject request missing model or input
- GIVEN a request body without `model` or with empty `input`
- WHEN `POST /v1/responses` is received
- THEN the server returns HTTP 400 with an OpenAI error schema `{"error": {"message": "...", "type": "invalid_request_error", "code": 400}}`.

### Requirement: Non-Streaming Responses Completion (`stream: false`)

When `stream` is `false` or omitted, the shim MUST aggregate all generated content and return HTTP 200 with an OpenAI Response object:
- `id`: string prefixed with `resp_` and unique UUID.
- `object`: `"response"`.
- `created`: integer Unix timestamp.
- `status`: `"completed"`.
- `model`: requested model identifier.
- `output`: list containing one message item:
  - `id`: string prefixed with `msg_`.
  - `type`: `"message"`.
  - `role`: `"assistant"`.
  - `content`: `[{"type": "output_text", "text": "<aggregated text>"}]`.
- `usage`: object containing `total_tokens`, `input_tokens`, and `output_tokens`.

#### Scenario: Non-streaming response generation
- GIVEN a valid non-streaming request to `POST /v1/responses`
- WHEN upstream completes generation
- THEN the server returns HTTP 200 with `status: "completed"` and output containing `output_text`.

### Requirement: Streaming Server-Sent Events Translation (`stream: true`)

When `stream` is `true`, the server MUST respond with `Content-Type: text/event-stream; charset=utf-8` and emit OpenAI Responses SSE events in strict sequence:
1. `event: response.created` with initial response object (`status: "in_progress"`).
2. `event: response.output_item.added` with output index 0 and message item structure.
3. `event: response.content_part.added` with part index 0 and type `output_text`.
4. Multiple `event: response.output_text.delta` with delta text string.
5. `event: response.content_part.done` with final text part.
6. `event: response.output_item.done` with completed message item.
7. `event: response.completed` with final response object (`status: "completed"`).

The shim MUST filter out upstream thought metadata blocks from output text deltas.

#### Scenario: Streaming response lifecycle
- GIVEN a valid `POST /v1/responses` request with `stream: true`
- WHEN upstream emits generation SSE lines
- THEN the server emits `response.created`, `response.output_item.added`, `response.content_part.added`, chunks of `response.output_text.delta`, `response.content_part.done`, `response.output_item.done`, and `response.completed`.

### Requirement: Responses Protocol Error Responses

Upstream and transformation errors MUST be serialized as OpenAI error responses: `{"error": {"message": "<str>", "type": "<error_type>", "code": <status_code>}}` matching the corresponding HTTP status code (400, 401, 403, 404, 429, 500, 503, 504).

#### Scenario: Handle upstream capacity exhaustion
- GIVEN upstream raises `CapacityExhaustedError` during Responses processing
- WHEN `POST /v1/responses` is processed
- THEN the server returns HTTP 503 with error type `api_error`.
