# Delta for Responses Shim

## MODIFIED Requirements

### Requirement: Responses Request Validation and Translation

The server MUST accept `POST /v1/responses` with JSON payload containing:
- `model`: optional string identifying the model. If omitted, empty, or set to `"auto"`, the shim MUST alias the model to `"gemini-3.8-flash-tiered"`.
- `input`: required list of input items or strings representing conversation history.
- `instructions`: optional string providing system/developer guidance.
- `stream`: optional boolean (default `false`).

The transform layer MUST translate the payload into Cloud Code Assist parameters:
- Model names `gemini-3.8-flash-high`, `gemini-3.8-flash`, and `auto` (or omitted/empty) MUST be mapped to `gemini-3.8-flash-tiered` with `thinkingLevel: "HIGH"`.
- `instructions` mapped to `systemInstruction.parts[].text`.
- `input` parsed and mapped to `contents`:
  - Items with `role: "user"` or string inputs mapped to role `user`.
  - Items with `role: "assistant"` mapped to role `model`.
  - Sub-blocks of type `input_text` extracted into turn text parts.
- Alternation and turn order rules MUST be enforced.
- Configures adaptive thinking according to model capabilities and model aliasing rules.
(Previously: Required non-empty model string without automatic aliasing or empty-model fallback to gemini-3.8-flash-tiered with HIGH thinking)

#### Scenario: Translate valid Codex Responses request
- GIVEN a `POST /v1/responses` request with `instructions`, `input` items, and target `model`
- WHEN the shim processes the request
- THEN it creates valid Cloud Code `systemInstruction` and `contents` structures
- AND passes them to the upstream client.

#### Scenario: Reject request missing input
- GIVEN a request body with empty `input` or invalid input structure
- WHEN `POST /v1/responses` is received
- THEN the server returns HTTP 400 with an OpenAI error schema `{"error": {"message": "...", "type": "invalid_request_error", "code": 400}}`.

#### Scenario: Model aliasing for Responses requests
- GIVEN a `POST /v1/responses` request with model set to `"gemini-3.8-flash-high"`, `"gemini-3.8-flash"`, `"auto"`, or omitted
- WHEN the shim processes the request
- THEN the upstream model is resolved to `"gemini-3.8-flash-tiered"`
- AND `thinkingConfig` contains `{"thinkingLevel": "HIGH"}`.
