# Feature Tasks: OpenCode como proveedor en las tarjetas de setup

Agregar una pestaña **OpenCode** a las tarjetas de los agentes que el bridge configura
contra un upstream (`claude`, `codex`, `hermes`, `pi`, `gentle-shell`, `openclaw`),
y que los `setup-*` correspondientes acepten `--provider opencode`.

## Specs

- **S1 — Alcance de tarjetas.** La pestaña `opencode` aparece SOLO en las tarjetas de
  clientes que se configuran contra un upstream del bridge: `claude`, `codex`, `hermes`,
  `pi`, `gentle-shell`, `openclaw`. NO aparece en la propia tarjeta de `opencode`
  (no tiene lógica inyectarle a sí mismo su propio upstream), ni en `cursor` (su propio
  upstream), ni en `freellmapi` (otro gateway, no consumidor del nuestro).
- **S2 — Backend.** Cada `setup-<cliente>` de S1 acepta `--provider opencode` y
  configura el cliente contra el bridge local con modelos `opencode/*` (free tier),
  usando el mismo patrón que ya existe para `agy`/`cursor`/`all`.
- **S3 — Modelos del picker.** Las opciones del selector de modelos de cada cliente
  para `opencode` son los modelos free de OpenCode con tag `[OpenCode]`, y el default
  es `opencode/pulse-alpha-free`.
- **S4 — Exclusion logica.** La tarjeta `opencode`, `cursor` y `freellmapi` nunca
  muestran la pestaña `opencode`.
- **S5 — TDD y release.** Test-first por cliente; suite completa verde; ruff+mypy
  limpios; bump de versión sincronizado en los 3 archivos (lección aprendida de
  v0.32.0→v0.33.0); conventional commits sin atribución IA; README test count.

## Tasks

- **T1** `claude` aprende `--provider opencode` (+ test). Commit aparte.
- **T2** `codex` aprende `--provider opencode` (+ test).
- **T3** `hermes` + `pi` aprenden `--provider opencode` (+ tests).
- **T4** `gentle-shell` + `openclaw` aprenden `--provider opencode` (+ tests).
- **T5** UI: pestaña `opencode` en las tarjetas de S1, excluyendo S4 (+ tests dashboard).
- **T6** Docs README + bump versión + release + push a main.

## Log

- **L1** (user, verbatim): "sumar opencode, pero no tiene logica que la tarjeta del propio opencode tenga opencode, no vamos a injectarle lo que es de el, tampoco creo que se tenga que podner en la tarjeta de 'Cursor' ni de 'FreeLLMAPI'. Entiendes?"
- **L2** (user decision): "Hacerlo completo (backend + UI)".
- **L3** (hallazgo): los setup-* hoy solo soportan provider agy/cursor/all; agregar opencode
  implica extender cada configurador, no solo la UI.
- **L4** (closure 2026-11-03): Feature complete.
  - Backend: `claude`, `codex`, `hermes`, `pi`, `gentle-shell`, `openclaw` configurators now accept `--provider opencode`, wiring the target agent to the local bridge with `opencode/*` free models and `opencode/pulse-alpha-free` as primary/default.
  - Helper: `opencode_provider_models()` added to `bridge/setup/common.py`.
  - UI: `_make_client_providers()` in `bridge/dashboard.py` adds the `opencode` tab (`OpenCode (Free)` / `OpenCode (Gratis)`) to eligible cards (`client_id != "opencode"`). Excluded from `opencode` card, `cursor` card, and `freellmapi` card.
  - i18n: `"tab_opencode"` wired into EN/ES dictionaries.
  - Quality: 1155 unit tests passing (100%), ruff and mypy 100% clean.
  - Release: version bumped to 0.34.0 across `bridge/__init__.py`, `pyproject.toml`, `install.sh`, `README.md`, and version-pinned tests.
