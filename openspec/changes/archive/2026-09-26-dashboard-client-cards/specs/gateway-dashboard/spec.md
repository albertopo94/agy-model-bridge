# Delta for Gateway Dashboard

## MODIFIED Requirements

### Requirement: Dark-Mode Dashboard Endpoint

The server MUST handle `GET /` and return HTTP 200 with `Content-Type: text/html; charset=utf-8`.
The HTML document MUST be self-contained with embedded CSS and JavaScript, requiring zero external CDN requests, fonts, or libraries.
The UI SHALL render in a Geist/Vercel dark-mode palette (`#000000`/`#0d0d0d` background, `#111111` container cards with `border-radius: 16px`, `#222222` subtle borders, and monospace code blocks).
The layout SHALL present client cards in a responsive 2-column grid on desktop screens, falling back to a single column on screens narrower than 768px.
(Previously: Slate background `#0f172a`, 10px rounded cards `#1e293b`, and single-column cards grid)

#### Scenario: Access root dashboard successfully
- GIVEN the bridge server is active on `127.0.0.1:8080`
- WHEN a user or browser sends `GET /`
- THEN the server returns HTTP 200 with `Content-Type: text/html; charset=utf-8`
- AND the body contains self-contained HTML with 16px radius cards, dark palette, and interaction scripts.

#### Scenario: Responsive grid layout on mobile viewport
- GIVEN a client browser viewport narrower than 768px
- WHEN `GET /` is rendered
- THEN the cards grid collapses into a single-column stacked layout without horizontal scroll overflow.

#### Scenario: Non-GET method on root path
- GIVEN a client sends `POST /`, `PUT /`, or `DELETE /`
- WHEN the request reaches the server
- THEN the server returns HTTP 404 or HTTP 405 error schema.

### Requirement: Interactive Client Configuration Cards

The dashboard MUST display 4 dedicated client configuration cards in a responsive 2-column grid:
1. **Claude Code**: Dedicated card for Anthropic Messages CLI (`BASE_URL` without `/v1`).
2. **Codex CLI**: Dedicated card for OpenAI Responses CLI (`wire_api = "responses"`, `BASE_URL` with `/v1`).
3. **Hermes Agent**: Dedicated card for NousResearch Hermes Agent CLI (`BASE_URL` with `/v1`).
4. **FreeLLMAPI**: Dedicated card for FreeLLMAPI gateway / Aider integration (`BASE_URL` with `/v1`).

Each card MUST feature a standardized two-tier setup structure:
- **Configuración automática**: Includes descriptive microcopy, a single-line command (`npx freellmapi setup-...` or CLI equivalent), and an independent copy button.
- **Conexión manual**: Includes descriptive microcopy, a formatted code block showing required `BASE_URL` and `API_KEY` (or environment variable exports), and an independent copy button.
- **Documentation link**: Card footer MUST include a clickable external link (`Documentación ↗`) pointing to the client's official documentation.

Embedded JavaScript MUST support click-to-copy for each copy button independently with visual feedback (e.g., "Copied!").
(Previously: 3 cards with single-snippet copy and no two-tier breakdown or doc links)

#### Scenario: Copy automatic setup command
- GIVEN the dashboard rendered in a browser
- WHEN a user clicks the copy button in the "Configuración automática" section of the Claude Code card
- THEN the single-line automatic command is copied to the clipboard
- AND the button displays temporary "Copied!" feedback.

#### Scenario: Copy manual connection parameters
- GIVEN the dashboard rendered in a browser
- WHEN a user clicks the copy button in the "Conexión manual" section of the Codex card
- THEN the formatted manual connection settings are copied to the clipboard
- AND the button displays temporary visual confirmation.

#### Scenario: Documentation footer navigation
- GIVEN any of the 4 client cards
- WHEN a user clicks the "Documentación ↗" footer link
- THEN the browser navigates to the external documentation URL in a new tab.

#### Scenario: Clipboard copy failure fallback
- GIVEN clipboard API is unavailable or restricted by browser permissions
- WHEN a user clicks any copy button
- THEN the target text remains selectable for manual copying without throwing unhandled exceptions.
