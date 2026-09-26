# Delta for Gateway Dashboard

## MODIFIED Requirements

### Requirement: Interactive Client Configuration Cards

The dashboard MUST display 4 dedicated client configuration cards in a responsive 2-column grid:
1. **Claude Code**: Dedicated card for Anthropic Messages CLI (`BASE_URL` without `/v1`).
2. **Codex CLI**: Dedicated card for OpenAI Responses CLI (`wire_api = "responses"`, `BASE_URL` with `/v1`).
3. **Hermes Agent**: Dedicated card for NousResearch Hermes Agent CLI (`BASE_URL` with `/v1`).
4. **FreeLLMAPI**: Dedicated card for FreeLLMAPI gateway / Aider integration (`BASE_URL` with `/v1`).

Each card MUST feature a standardized two-tier setup structure:
- **Configuración automática**: Includes descriptive microcopy, a single-line command, and an independent copy button. For **Claude Code**, the command MUST be `python3 -m bridge setup-claude`. For **Codex CLI**, the command MUST be `python3 -m bridge setup-codex`.
- **Conexión manual**: Includes descriptive microcopy, a formatted code block showing required `BASE_URL` and `API_KEY` (or environment variable exports), and an independent copy button.
- **Documentation link**: Card footer MUST include a clickable external link (`Documentación ↗`) pointing to the client's official documentation.

Embedded JavaScript MUST support click-to-copy for each copy button independently with visual feedback (e.g., "Copied!").
(Previously: Automatic configuration commands used ad-hoc shell export chains or external commands rather than native bridge setup CLI subcommands)

#### Scenario: Copy automatic setup command for Claude Code
- GIVEN the dashboard rendered in a browser
- WHEN a user clicks the copy button in the "Configuración automática" section of the Claude Code card
- THEN the clipboard receives `python3 -m bridge setup-claude`
- AND the button displays temporary "Copied!" feedback.

#### Scenario: Copy automatic setup command for Codex CLI
- GIVEN the dashboard rendered in a browser
- WHEN a user clicks the copy button in the "Configuración automática" section of the Codex CLI card
- THEN the clipboard receives `python3 -m bridge setup-codex`
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
