# Delta for Anthropic Shim

## MODIFIED Requirements

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
(Previously: Required non-empty model identifier without automatic aliasing or empty-model fallback to gemini-3.8-flash-tiered with HIGH thinking)

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
