# Cloud Code Client Specification

## Purpose

Provide a pure standard library HTTP gateway to Google Cloud Code Assist (`daily-cloudcode-pa.googleapis.com`) for project discovery, model enumeration, and SSE content generation streaming.

## Requirements

### Requirement: Upstream Transport and Request Formatting

The client MUST use `urllib.request` without external dependencies. Every request to `https://daily-cloudcode-pa.googleapis.com` MUST include headers: `Authorization: Bearer <token>`, `Content-Type: application/json`, and `User-Agent: antigravity/1.0`. Requests SHALL respect a configurable network timeout.

#### Scenario: Request contains required headers
- GIVEN a valid bearer token
- WHEN any upstream endpoint is called
- THEN the client attaches `Authorization: Bearer <token>`, `Content-Type: application/json`, and `User-Agent: antigravity/1.0`.

### Requirement: Project and Tier Discovery (`loadCodeAssist`)

The client SHALL send `POST /v1internal:loadCodeAssist` with payload `{"ideType": "ANTIGRAVITY", "platform": "PLATFORM_UNSPECIFIED", "pluginType": "GEMINI"}`. The client MUST extract and return the active `project` identifier (e.g. `aicode-consumers`) and tier from the response.

#### Scenario: Discover project and tier
- GIVEN valid authentication
- WHEN `load_code_assist()` is executed
- THEN the client returns a dictionary containing the active project identifier and user tier.

### Requirement: Model Catalog Retrieval (`fetchAvailableModels`)

The client SHALL send `POST /v1internal:fetchAvailableModels` containing the resolved project identifier. The client MUST return the list of available model descriptors and metadata.

#### Scenario: Retrieve available models catalog
- GIVEN an active project ID `aicode-consumers`
- WHEN `fetch_available_models(project="aicode-consumers")` is called
- THEN the client returns the catalog of supported models including identifiers and capabilities.

### Requirement: SSE Content Generation Streaming (`streamGenerateContent`)

The client SHALL send `POST /v1internal:streamGenerateContent?alt=sse` with request payload specifying `project`, `model`, and `contents`. The client MUST yield raw Server-Sent Events lines iteratively as they arrive without buffering the entire HTTP response body.

#### Scenario: Stream generation chunks
- GIVEN a valid generation payload
- WHEN `stream_generate_content(...)` is called
- THEN the client yields raw SSE data lines sequentially as streamed by upstream.

### Requirement: Upstream Error Mapping

The client MUST map upstream HTTP status codes and transport errors to typed exceptions:
- HTTP 400 SHALL raise `InvalidRequestError`.
- HTTP 401/403 SHALL raise `AuthenticationError`.
- HTTP 404 SHALL raise `ModelNotFoundError`.
- HTTP 429 SHALL raise `RateLimitError`.
- HTTP 503 SHALL raise `CapacityExhaustedError`.
- Transport timeouts SHALL raise `UpstreamTimeoutError`.

#### Scenario: Handle upstream 429 rate limit
- GIVEN upstream returns HTTP 429 Too Many Requests
- WHEN any client method is invoked
- THEN the client raises `RateLimitError` containing upstream error details.

#### Scenario: Handle upstream 503 capacity exhaustion
- GIVEN upstream returns HTTP 503 Service Unavailable for an overloaded model
- WHEN `stream_generate_content(...)` is called
- THEN the client raises `CapacityExhaustedError`.
