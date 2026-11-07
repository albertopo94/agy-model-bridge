# Feature: Rebrand to Abridge (abridge / abridge-ai)
Zero-downtime transition preserving running agent authorization and backwards compatibility.

## Specs
- **S1** (user verbatim): "Crees que ahora mismo tiene el mejor nombre posible? el actual nombre creo que le quedaba bien cuando solo era Google Antigravity cli (agy), pero ahora creo que es algo mas que eso."
- **S2** (user verbatim): "me suena bien lo de "Abridge" ... solo lo uso yo por ahora ya que no lo he compartido al publico hoy, pero luego de este cambio puede que si lo haga"
- **S3** (user verbatim): "que pasa con los agentes donde estoy usando ahora mismo la version actual ? uno es otro repo y otro es ahora mismo aqui hablando contigo. el otro agente en el otro repo y tu aqui se quedaran colgados despues del cambio?" -> Zero-downtime migration: state directory `~/.abridge` adopts `~/.agy-bridge/api_key` automatically; active port 24980 and endpoints remain unchanged; backwards compatibility aliases `agy-bridge` and `agy-model-bridge` preserved.
- **S4**: Package metadata in `pyproject.toml` updated to `abridge-ai` (v0.35.0), primary CLI `abridge`, aliases `agy-bridge` and `agy-model-bridge`.
- **S5**: Dashboard, i18n, CLI prompts, install/lifecycle scripts, and docs updated with `abridge` as primary while preserving aliases.

## Tasks
- [x] **T1** (S3): State directory resolution and credential continuity (`~/.abridge` with fallback/adoption from `~/.agy-bridge`). Route: inline. Commit: e97e8c2.
- [x] **T2** (S4): CLI entrypoints, prog_base dynamic resolution, and `pyproject.toml` package script configuration. Route: inline. Commit: 18ea2aa.
- [x] **T3** (S5): Dashboard snippets, i18n labels, and client configurators updated to `abridge`. Route: inline. Commit: 9c120a3.
- [x] **T4** (S3, S4, S5): Documentation, README, AGENTS.md, test count synchronization, and SemVer bump to v0.35.0. Route: inline. Commit: 1048305.

> **Slice boundary**: Commits e97e8c2, 18ea2aa, 9c120a3 conclude the runtime implementation slice (~558 lines). Commit 1048305 concludes the release documentation and versioning slice (~254 lines). All 4 tasks complete, 1,161 tests passing (100%).

## Log
- **L1**: User asked if the current name is best suited given multi-provider evolution.
- **L2**: Proposed "Abridge" (CLI `abridge`, PyPI `abridge-ai`) with zero-downtime migration and backwards-compatible aliases.
- **L3**: User confirmed and asked about active agents in running sessions.
- **L4**: Clarified socket/auth architecture and user authorized proceeding ("si").
