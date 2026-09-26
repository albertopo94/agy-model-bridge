# Anthropic Shim Specification

## Purpose

Expose an Anthropic Messages API (`POST /v1/messages`) translating Anthropic request payloads and Server-Sent Events to and from Google Cloud Code Assist format for Claude Code CLI and Anthropic SDKs.

## Requirements

### Requirement: Messages Request Validation and Translation

The server MUST accept `POST /v1/messages` with JSON payload containing:
- `model`: optional string identifying the target model. If omitted, empty, or set to `"auto"`, the shim MUST alias the model to `"gemini-3.8-flash-tiered"`.
- `messages`: required non-empty list of turn objects with `role` (`user` or `assistant`) and `content` (string or array of text blocks).
- `system`: optional string or array of system blocks.
- `max_tokens`: optional integer defining generation limit.
- `stream`: optional boolean (default `false`).

The transform layer MUST translate the payload into Cloud Code Assist parameters:
- Model names `gemini-3.8-flash-high`, `gemini-3.8-flash`, and `auto` (or omitted/empty) MUST be mapped to `gemini-3.8-flash-tiered` with `thinkingLevel: "HIGH"`.
- `system` mapped to `systemInstruction.parts[].text`.
- `messages` mapped to `contents` (`user` -> `user`, `assistant` -> `model`). Alternation and leading user turn rules MUST be enforced.
- `max_tokens` mapped to `generationConfig.maxOutputTokens`.
- Configures adaptive thinking according to model capabilities and model aliasing rules.

#### Scenario: Translate valid Anthropic request
- GIVEN a `POST /v1/messages` request with system prompt, messages array, and `max_tokens: 1024`
- WHEN the shim processes the request
- THEN it generates valid Cloud Code `contents`, `systemInstruction`, and `generationConfig`
- AND forwards the call to `CloudCodeClient`.

#### Scenario: Reject malformed Anthropic request
- GIVEN a request with empty `messages` or invalid non-array messages payload
- WHEN `POST /v1/messages` is received
- THEN the server returns HTTP 400 with Anthropic error schema `{"type": "error", "error": {"type": "invalid_request_error", "message": "..."}}`.

#### Scenario: Model aliasing for flash-high and auto requests
- GIVEN a `POST /v1/messages` request with model set to `"gemini-3.8-flash-high"`, `"gemini-3.8-flash"`, `"auto"`, or omitted
- WHEN the shim processes the request
- THEN the upstream model is resolved to `"gemini-3.8-flash-tiered"`
- AND `thinkingConfig` contains `{"thinkingLevel": "HIGH"}`.

### Requirement: Non-Streaming Messages Completion (`stream: false`)

When `stream` is `false` or omitted, the shim MUST aggregate all upstream generation parts and return HTTP 200 with an Anthropic Messages response object:
- `id`: string prefixed with `msg_` and unique identifier.
- `type`: `"message"`.
- `role`: `"assistant"`.
- `model`: requested model name.
- `content`: array containing a single text block `[{"type": "text", "text": "<generated text>"}]`.
- `stop_reason`: `"end_turn"` or `"max_tokens"`.
- `stop_sequence`: `null`.
- `usage`: object containing `input_tokens` and `output_tokens`.

#### Scenario: Non-streaming message generation
- GIVEN a valid non-streaming request to `POST /v1/messages`
- WHEN upstream completes generation with text `"Hello Claude"`
- THEN the server returns HTTP 200 with `content: [{"type": "text", "text": "Hello Claude"}]` and `stop_reason: "end_turn"`.

### Requirement: Streaming Server-Sent Events Translation (`stream: true`)

When `stream` is `true`, the server MUST respond with `Content-Type: text/event-stream; charset=utf-8` and emit Anthropic-compliant SSE events in strict order:
1. `event: message_start` with initial message metadata and empty content.
2. `event: content_block_start` with `index: 0` and empty text block.
3. Multiple `event: content_block_delta` with `delta.type: "text_delta"` and chunk text.
4. `event: content_block_stop` with `index: 0`.
5. `event: message_delta` with `delta.stop_reason: "end_turn"` and output usage tokens.
6. `event: message_stop`.

The shim MUST filter out upstream thought metadata blocks (`thought: true` or `thoughtSignature`) from text deltas.

#### Scenario: Full streaming event lifecycle
- GIVEN a valid request with `stream: true`
- WHEN upstream emits token chunks sequentially
- THEN the server streams `message_start`, `content_block_start`, series of `content_block_delta`, `content_block_stop`, `message_delta`, and terminates with `message_stop`.

### Requirement: Anthropic Protocol Error Responses

Upstream and adapter errors MUST be serialized as Anthropic error schemas: `{"type": "error", "error": {"type": "<type>", "message": "<str>"}}` with corresponding HTTP status codes (400, 401, 403, 404, 429, 500, 503, 504).

#### Scenario: Upstream authentication failure
- GIVEN upstream raises `AuthenticationError` during message processing
- WHEN `POST /v1/messages` is called
- THEN the server returns HTTP 401 with `error.type: "authentication_error"`.
