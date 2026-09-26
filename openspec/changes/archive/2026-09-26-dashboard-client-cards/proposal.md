# Proposal: FreeLLMAPI Standard Client Cards for Dashboard

## Intent

Align the local gateway dashboard (`GET /`) with FreeLLMAPI client setup card standards. Replace the 3-card layout with 4 dedicated client cards featuring two-tier configuration (automatic CLI vs. manual parameters), documentation links, and Vercel dark aesthetics.

## Scope

### In Scope
- 4 dedicated cards: Claude Code, Codex CLI, Hermes Agent, and FreeLLMAPI / Aider.
- Two-tier layout: "Configuración automática" (`npx` setup) and "Conexión manual" (`BASE_URL` + `API_KEY`).
- One-click copy buttons with visual feedback for both tiers.
- Card footers with "Documentación ↗" links.
- Styling: Geist/Vercel dark mode, 16px radius, `#0d0d0d`/`#111111` surfaces, `#222222` borders, 2-column grid.

### Out of Scope
- Brand SVG logos (postponed; using clean typography placeholders).
- Backend protocol changes (`/v1/messages` and `/v1/responses` remain unchanged).
- External npm or CDN runtime dependencies.

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `gateway-dashboard`: Refactor to 4 dedicated cards with two-tier setup flows, documentation links, and 16px dark styling.
- `smoke-test`: Extend assertions to verify all 4 client cards in dashboard HTML.

## Approach

- Update `render_dashboard` in `bridge/dashboard.py` to render a 2-column grid with 4 cards.
- Add snippet templates for automatic commands (`npx freellmapi setup-...`) and manual connection settings.
- Refactor CSS for 16px border-radius, dark surfaces, and 768px responsive breakpoint.
- Update vanilla JS copy handler to support multiple buttons per card.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `bridge/dashboard.py` | Modified | 4-card two-tier layout and 16px styling |
| `tests/test_dashboard.py` | Modified | Assert 4 cards, two-tier content, and copy |
| `scripts/smoke_test.py` | Modified | Verify 4 client cards in HTML |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Layout overflow on small screens | Low | Responsive 1-column mobile breakpoint at 768px |
| Multi-button copy conflicts | Low | Parameterize `copySnippet` with unique target IDs |
| Test assertion regressions | Low | Preserve existing keywords while adding Hermes assertions |

## Rollback Plan

Revert git commit. Changes are isolated to the dashboard presentation layer.

## Dependencies

- Python 3 standard library only (`http.server`, `html`, `urllib`).
- Browser Clipboard API.

## Success Criteria

- [ ] `GET /` displays 4 dedicated client cards in a responsive 2-column grid.
- [ ] Each card provides "Configuración automática" and "Conexión manual" copy blocks.
- [ ] Card footers link to official documentation.
- [ ] UI features 16px border radius and Vercel dark palette.
- [ ] `python3 -m unittest` passes 100%.
- [ ] `python3 scripts/smoke_test.py` passes all checks.
