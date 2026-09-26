# Tasks: FreeLLMAPI Standard Client Cards for Dashboard

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | ~180-260 lines |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: stacked-to-main
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|---|---|---|---|
| 1 | FreeLLMAPI standard client cards, 2-column grid & doc links | PR 1 | Single deliverable covering Phases 1-4 within the 400-line review budget |

## Phase 1: Card Component Schema & Declarative Rendering

- [x] 1.1 [RED] Add unit tests in `tests/test_dashboard.py` asserting all 4 client cards ("Claude Code", "Codex CLI", "Hermes Agent", "FreeLLMAPI") and their two-tier setup blocks ("Configuración automática", "Conexión manual").
- [x] 1.2 [GREEN] Define `CLIENT_CARDS` declarative list and update `render_dashboard()` in `bridge/dashboard.py` to loop through cards and interpolate setup snippets.
- [x] 1.3 [REFACTOR] Clean up card snippet generators and template string interpolation in `bridge/dashboard.py` for minimal memory overhead.

## Phase 2: Responsive 2-Column Grid & 16px Vercel Styling

- [x] 2.1 [RED] Add unit tests in `tests/test_dashboard.py` asserting 16px border-radius, dark surfaces (`#000000`, `#111111`, `#222222`), and the 768px responsive CSS media query.
- [x] 2.2 [GREEN] Update CSS in `bridge/dashboard.py` to implement the responsive 2-column CSS Grid (`repeat(2, minmax(0, 1fr))`) and Vercel dark aesthetics.
- [x] 2.3 [REFACTOR] Streamline CSS stylesheet rules and variable definitions in `bridge/dashboard.py`.

## Phase 3: Independent Copy Handlers & Documentation Links

- [x] 3.1 [RED] Add unit tests in `tests/test_dashboard.py` asserting independent snippet IDs (`auto` and `manual` for each card), clipboard JavaScript, and "Documentación ↗" anchor tags with correct external URLs.
- [x] 3.2 [GREEN] Implement parameterized `copySnippet(btn, id)` in vanilla JS and render card footer documentation links in `bridge/dashboard.py`.
- [x] 3.3 [REFACTOR] Refactor JavaScript clipboard copy logic with robust fallback for unsupported or restricted browser environments.

## Phase 4: Multi-Protocol Smoke Test Update & Full Suite Verification

- [x] 4.1 Update stage [3/9] in `scripts/smoke_test.py` to verify presence of all 4 client cards, two-tier setup headers, and documentation links.
- [x] 4.2 Run integration test assertions in `tests/test_server.py` to confirm root route (`GET /`) passes through to new dashboard HTML.
- [x] 4.3 Run full test suite (`python3 -m unittest`) and verify 100% pass across all test modules with zero regressions.
