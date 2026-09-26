# Delta for OpenAI Adapter

## ADDED Requirements

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
