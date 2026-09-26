# OpenAI Adapter Specification

## Purpose

Serve an OpenAI-compatible HTTP interface translating standard chat completion requests to and from Google Cloud Code Assist format, with concurrent request handling and real-time SSE streaming.

## Requirements

### Requirement: Health and Model Discovery Endpoints

The server MUST use `http.server.ThreadingHTTPServer` to process concurrent requests.
- `GET /healthz` MUST respond with HTTP 200 and JSON body `{"status": "ok"}`.
- `GET /v1/models` MUST respond with HTTP 200 and standard OpenAI list payload `{"object": "list", "data": [{"id": "<model_id>", "object": "model", "created": 1700000000, "owned_by": "google"}]}`.

#### Scenario: Health check returns status OK
- GIVEN the bridge server is running
- WHEN a client sends `GET /healthz`
- THEN the server returns HTTP 200 with `{"status": "ok"}`.

#### Scenario: List models in OpenAI format
- GIVEN available models reported by upstream client
- WHEN a client sends `GET /v1/models`
- THEN the server returns HTTP 200 with an OpenAI-compliant list of model descriptors.

### Requirement: Request Validation and Role Translation

The server MUST accept `POST /v1/chat/completions` with JSON payload containing `model` and `messages`. The transform layer MUST validate that `messages` is a non-empty list of objects with `role` and `content`.
The transform layer SHALL map:
- `system` role to `systemInstruction` parts or initial context.
- `user` role to Cloud Code role `user`.
- `assistant` role to Cloud Code role `model`.

#### Scenario: Valid request translation
- GIVEN an OpenAI completion request with system, user, and assistant messages
- WHEN the adapter parses the payload
- THEN it transforms the messages into Cloud Code `contents` with roles `user` and `model`, placing system instructions appropriately.

#### Scenario: Reject invalid request
- GIVEN a request missing `model` or with empty `messages`
- WHEN `POST /v1/chat/completions` is received
- THEN the server responds with HTTP 400 and an OpenAI error schema `{"error": {"message": ..., "type": "invalid_request_error", "code": 400}}`.

### Requirement: Real-Time SSE Streaming Completion (`stream: true`)

When `stream` is `true`, the server MUST respond with `Content-Type: text/event-stream` and chunked transfer. The server MUST flush each `chat.completion.chunk` event immediately upon receipt of upstream text deltas. The transform layer MUST filter out upstream thought metadata blocks (`thought: true` or `thoughtSignature`) and only forward generated text. Upon completion, the server MUST emit a final chunk with `finish_reason: "stop"` followed by `data: [DONE]\n\n`.

#### Scenario: Real-time streaming chunks with thought filtering
- GIVEN an upstream SSE stream emitting text deltas and thought metadata blocks
- WHEN `POST /v1/chat/completions` is requested with `stream: true`
- THEN each text delta is immediately flushed as `data: {"object": "chat.completion.chunk", ...}\n\n`
- AND thought blocks without content are discarded
- AND the stream closes with `data: [DONE]\n\n`.

### Requirement: Non-Streaming Completion (`stream: false`)

When `stream` is `false` or omitted, the server SHALL consume upstream events, assemble the full generated text content, and return a single `chat.completion` JSON object with HTTP 200 and standard OpenAI choices structure.

#### Scenario: Non-streaming full response
- GIVEN a valid chat completion request with `stream: false`
- WHEN the upstream generation finishes
- THEN the server returns HTTP 200 with a complete `chat.completion` JSON object containing aggregated text.

### Requirement: Standardized OpenAI Error Responses

The server MUST catch all internal and upstream exceptions and serialize them into standard OpenAI error responses: `{"error": {"message": "<str>", "type": "<error_type>", "code": <status_code>}}` matching the appropriate HTTP status code (400, 401, 404, 429, 500, 503, 504).

#### Scenario: Upstream rate limit error response
- GIVEN the upstream client raises `RateLimitError`
- WHEN `POST /v1/chat/completions` is processed
- THEN the server returns HTTP 429 with error type `rate_limit_error`.

### Requirement: Gateway Dashboard Route Handling

The server MUST handle `GET /` requests by dispatching to the embedded dashboard renderer and returning HTTP 200 with self-contained HTML.
The server MUST preserve existing endpoints `GET /healthz` and `GET /v1/models` without modification.

#### Scenario: Route root path to dashboard
- GIVEN the bridge server is running
- WHEN a client sends `GET /`
- THEN the server returns HTTP 200 with `Content-Type: text/html; charset=utf-8`
- AND the body contains the gateway dashboard interface.

### Requirement: Multi-Protocol Dispatching

The server MUST expand its routing table to accept requests across distinct client protocols:
- `POST /v1/messages`: Dispatches to `anthropic-shim` handler for Claude Code CLI requests.
- `POST /v1/responses`: Dispatches to `responses-shim` handler for Codex CLI requests.
- `POST /v1/chat/completions`: Retains existing OpenAI Chat Completions handling.

All routes SHALL share the same underlying `CloudCodeClient`, `KeychainTokenProvider`, and background thread pool.

#### Scenario: Dispatch to Anthropic Messages shim
- GIVEN an active bridge server
- WHEN a client sends `POST /v1/messages`
- THEN the server invokes the Anthropic handler and streams or returns Anthropic formatted responses.

#### Scenario: Dispatch to OpenAI Responses shim
- GIVEN an active bridge server
- WHEN a client sends `POST /v1/responses`
- THEN the server invokes the Responses handler and streams or returns Responses formatted output.

### Requirement: Adaptive Model Reasoning and Thinking Configuration

When constructing `generationConfig` for upstream generation requests across all endpoints (`/v1/chat/completions`, `/v1/messages`, `/v1/responses`), the transform layer MUST dynamically inspect the requested `model` identifier:
- If the model name contains `-high` (e.g. `gemini-3.1-pro-high`): SHALL configure `thinkingConfig` with `thinkingLevel: "HIGH"`.
- If the model name contains `-medium`: SHALL configure `thinkingConfig` with `thinkingLevel: "MEDIUM"`.
- If the model name contains `-low`: SHALL configure `thinkingConfig` with `thinkingLevel: "LOW"`.
- If the model name contains `-thinking`: SHALL enable thinking with appropriate budget allocation.
- For all other standard or non-reasoning Gemini models: SHALL default `thinkingBudget: 0` unless explicitly overridden by request parameters, preventing invisible thought tokens from starving response length and returning empty bodies.
- Explicit thinking parameters supplied by the client in the request body MUST take precedence over model-name inferred defaults.

#### Scenario: Reasoning model configures thinking level
- GIVEN a request specifying model `gemini-3.1-pro-high`
- WHEN `openai_to_cloudcode_request` generates the upstream payload
- THEN `generationConfig.thinkingConfig` contains `thinkingLevel: "HIGH"`.

#### Scenario: Standard model defaults to zero thinking budget
- GIVEN a request specifying a standard Gemini model without reasoning keywords
- WHEN the upstream generation config is built
- THEN `generationConfig.thinkingConfig.thinkingBudget` is set to `0` to prevent token starvation.

#### Scenario: Explicit client thinking override
- GIVEN a request providing explicit `thinking` parameters in the payload
- WHEN `generationConfig` is constructed
- THEN client-specified values override heuristic defaults.
