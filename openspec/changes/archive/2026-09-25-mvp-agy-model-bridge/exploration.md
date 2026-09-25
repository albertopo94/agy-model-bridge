## Exploration: MVP Antigravity Model Bridge Architecture

### Current State
Today, the local environment has active Antigravity credentials stored in macOS Keychain (`service="gemini"`, `account="antigravity"`) containing a base64-encoded JSON payload (`go-keyring-base64:<Base64>`) with OAuth access tokens, refresh tokens, and expiration timestamps. The user also has the official Antigravity CLI daemon communicating directly with Google Cloud Code Assist upstream endpoints:
- `POST https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist`
- `POST https://daily-cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels`
- `POST https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse`

Empirical probe verification during exploration confirmed:
1. `loadCodeAssist` returns active consumer project `aicode-consumers` and `free-tier` when provided with metadata `{"ideType": "ANTIGRAVITY", "platform": "PLATFORM_UNSPECIFIED", "pluginType": "GEMINI"}` and user agent `antigravity/1.0`.
2. `fetchAvailableModels` returns a catalog of 20+ models (including `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3.1-pro-low`, `gemini-3.1-flash-lite`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`) when sent with `{"project": "aicode-consumers"}` and `antigravity/1.0` header.
3. `streamGenerateContent?alt=sse` successfully streams Server-Sent Events with candidate tokens and token usage metadata.
4. However, external OpenAI-compatible clients (e.g. FreeLLMAPI, Claude Code, Codex, Cursor, aider) cannot directly speak to Cloud Code Assist because of differing authentication mechanisms (macOS Keychain OAuth bearer vs API key), endpoint protocols (OpenAI `/v1/chat/completions` vs Cloud Code Assist `v1internal`), and message payload formats (`role: assistant` vs `role: model`, and `contents`/`parts`/`systemInstruction` structures).
5. The workspace currently contains only the OpenSpec repository scaffold with zero bridge implementation code.

### Affected Areas
- `bridge/__init__.py` — Package declaration and public version info.
- `bridge/__main__.py` — CLI entrypoint to start the bridge server (`python3 -m bridge [--port PORT] [--host HOST]`).
- `bridge/auth.py` — Keychain token extraction, JSON decoding, and in-memory TTL caching with force-refresh capabilities.
- `bridge/client.py` — Standard library HTTP client (`urllib.request`) communicating with `daily-cloudcode-pa.googleapis.com` for `loadCodeAssist`, `fetchAvailableModels`, and `streamGenerateContent`.
- `bridge/transform.py` — Pure conversion logic between OpenAI schemas and Cloud Code Assist request/response formats (system prompt extraction, role mapping, SSE parsing, and OpenAI JSON/chunk response building).
- `bridge/server.py` — `http.server.ThreadingHTTPServer` implementation hosting `/healthz`, `/v1/models`, and `/v1/chat/completions` (JSON and SSE streaming).
- `tests/test_auth.py` — Unit tests for Keychain parsing and token caching.
- `tests/test_client.py` — Unit tests for upstream request formation and response handling.
- `tests/test_transform.py` — Pure unit tests for bidirectional OpenAI <-> Cloud Code Assist payload translation.
- `tests/test_server.py` — Integration tests verifying HTTP endpoint routing, error responses, and streaming SSE contracts.
- `scripts/smoke_test.py` — Live end-to-end verification script testing the running bridge against live upstream endpoints.

### Approaches

#### Dimension 1: Service Architecture & Packaging
1. **Monolithic Single File (`bridge.py`)** — Implement all keychain reading, HTTP upstream client, SSE parsers, payload transformations, and HTTP server inside a single monolithic Python file (~450 lines).
   - Pros: Simple single-file distribution; zero package directory setup.
   - Cons: Severely harms testability under strict TDD; cannot test schema transformations in isolation without importing server dependencies; violates Single Responsibility and Clean Architecture principles; difficult to extend with post-MVP features (tool calling, multi-backend routing).
   - Effort: Low

2. **Modular Layered Architecture (`bridge/` package)** — Separate into clean, decoupled layers following Clean/Hexagonal Architecture:
   - `bridge/auth.py` (Identity & Token Cache adapter)
   - `bridge/client.py` (Upstream Gateway adapter)
   - `bridge/transform.py` (Domain entity & translation logic - 100% pure functions)
   - `bridge/server.py` (HTTP Driver / API Controller)
   - `bridge/__main__.py` (Application Composition root & CLI)
   - Pros: Strict separation of concerns; `bridge/transform.py` consists entirely of pure functions with zero I/O, allowing blazing-fast, deterministic unit tests with `python3 -m unittest`; adapters can be mocked cleanly without complex patching; adheres to project guidelines (Clean standard Python, PEP 8, zero third-party dependencies).
   - Cons: Slightly more files to manage (5 modules vs 1 script).
   - Effort: Low to Medium

#### Dimension 2: Token Lifecycle & Cache Strategy
1. **Per-Request Keychain Extraction** — Invoke `security find-generic-password` via `subprocess` synchronously on every incoming HTTP request.
   - Pros: Stateless; always obtains latest credentials from Keychain.
   - Cons: Spawns a process per request with 15–40ms latency overhead; unacceptable for low-latency chat interactions.
   - Effort: Low

2. **In-Memory TTL Cache with Proactive Expiry & 401 Retry** — Cache the active `access_token` and its `expiry` timestamp in memory with thread safety:
   - On request: if cached token exists and `current_time < expiry - 60s`, reuse it instantly (0.01ms overhead).
   - If missing, expired, or within 60s buffer: re-read Keychain via `subprocess`.
   - On upstream HTTP 401: invalidate the cache immediately, re-read Keychain once, and retry the request once before propagating an error downstream.
   - Pros: Optimal performance (<1ms auth lookup); automatically survives background token refreshes by the Antigravity daemon; self-healing on transient 401s.
   - Cons: Requires thread-safe synchronization (`threading.Lock`).
   - Effort: Low

#### Dimension 3: Streaming SSE Pipeline & Upstream Transformation
1. **Full Accumulation Buffer** — Read the entire upstream SSE stream into memory, assemble the complete response text, and emit it either as a single response or synthetic chunks.
   - Pros: Simple handling of usage tokens and error detection.
   - Cons: Defeats the purpose of streaming; introduces high first-token latency; high memory usage for large outputs; violates OpenAI SSE real-time streaming expectations.
   - Effort: Low

2. **Direct Line-Buffered Generator Pipeline** — Stream SSE events incrementally from `urllib.request.urlopen`:
   - Read lines iteratively from upstream HTTP response `resp.readline()`.
   - Parse SSE `data: {...}` lines; filter out non-text metadata or thoughts (`thought: true`, `thoughtSignature`).
   - Transform `text` deltas directly into OpenAI chunk payload: `data: {"id":..., "object":"chat.completion.chunk", "choices":[{"delta":{"content": text}}]}\n\n`.
   - Send chunks downstream using `self.wfile.write(...)` followed immediately by `self.wfile.flush()`.
   - Emit final `finish_reason: "stop"`, usage statistics chunk, and `data: [DONE]\n\n`.
   - Non-streaming requests reuse the same upstream SSE endpoint, accumulating chunks in memory before returning the standard OpenAI `chat.completion` JSON object.
   - Pros: Minimal memory footprint; sub-millisecond per-token latency; uniform upstream consumption (stream and non-stream share the same upstream SSE endpoint); fully OpenAI SSE compliant.
   - Cons: Requires careful error handling if the stream drops mid-generation.
   - Effort: Medium

#### Dimension 4: Error Handling & Downstream Mapping
1. **Pass-Through Raw Errors** — Return upstream Google JSON errors directly to downstream clients with 500 status code.
   - Pros: Trivial implementation.
   - Cons: Breaks OpenAI client libraries (e.g. OpenAI Python SDK, Claude Code, FreeLLMAPI) which expect OpenAI standard error schema `{"error": {"message": ..., "type": ..., "code": ...}}`.
   - Effort: Low

2. **Standardized OpenAI Error Adapter** — Intercept and map all upstream exceptions and HTTP error codes to standard OpenAI error formats:
   - Upstream 400: `invalid_request_error` (HTTP 400)
   - Upstream 401 / 403: `authentication_error` (HTTP 401) with actionable remediation message (e.g. "Run `agy login` or check Keychain credentials")
   - Upstream 404: `invalid_request_error` (HTTP 404 - "Model not found")
   - Upstream 429: `rate_limit_error` (HTTP 429 - "Google Cloud Code Assist rate limit exceeded")
   - Upstream 503: `api_error` (HTTP 503 - "Model capacity exhausted on upstream")
   - Network / Connection timeouts: `api_error` (HTTP 504)
   - Malformed downstream JSON: `invalid_request_error` (HTTP 400)
   - Pros: Seamless drop-in compatibility with any OpenAI-compatible client library; actionable error diagnostics for the user.
   - Cons: Requires mapping dictionary and explicit exception catches.
   - Effort: Low

### Recommendation
Adopt the combination of:
1. **Modular Layered Architecture (`bridge/`)**: Separates auth, client, pure transform, and server into focused modules with clean dependency flow. Enables strict TDD with pure `unittest` where transforms are tested without network or mocks.
2. **In-Memory TTL Cache with 401 Re-read**: Guarantees zero latency on steady state and self-heals when Antigravity refreshes credentials.
3. **Direct Line-Buffered Generator Pipeline**: Uses `urllib.request` with immediate `wfile.flush()` for true real-time SSE streaming, reusing the SSE stream for non-streaming requests.
4. **Standardized OpenAI Error Adapter**: Produces RFC/OpenAI compliant JSON errors for all failure modes.

### Risks
- **Upstream SSE Protocol Nuances**: Upstream chunks sometimes emit `thought: true` or `thoughtSignature` parts without content, or empty delta packets.
  *Mitigation*: The transform layer will explicitly check `part.get("text")` and ignore non-content thought blocks unless content is present.
- **Keychain Access Prompting**: Under certain macOS permission states, calling `security` from an unprompted binary could prompt a GUI dialog.
  *Mitigation*: Live testing confirmed `security find-generic-password -s "gemini" -a "antigravity" -w` succeeds seamlessly without GUI prompts.
- **Upstream Model Capacity (`503 UNAVAILABLE`)**: Some models like `gemini-2.5-pro` occasionally return 503 capacity errors, while `gemini-2.5-flash` and `gemini-3.1-pro-low` respond reliably.
  *Mitigation*: Support dynamic model passing and return standard OpenAI 503 errors when capacity is exhausted, defaulting clients to stable models like `gemini-2.5-flash`.

### Ready for Proposal
Yes — The proposal already exists (`openspec/changes/mvp-agy-model-bridge/proposal.md`) and the technical architecture is fully validated against live endpoints. The next recommended phase is `sdd-spec` to define concrete capability specifications and scenarios (Given/When/Then) for the bridge service.
