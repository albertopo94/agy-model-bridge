# Proposal: Native Client Setup CLI & Gemini 3.8 Flash High Aliasing

## Intent

Configuring terminal AI agents (Claude Code, Codex CLI) manually is error-prone and risks corrupting user configs. Google Cloud Code deprecates older models, requiring `gemini-3.8-flash-tiered` with `thinkingLevel: HIGH`. This change provides safe setup subcommands and seamless model aliasing.

## Scope

### In Scope
- `bridge/setup.py`: `setup-claude` and `setup-codex` CLI subcommands wired into `bridge/__main__.py`.
- Surgical update of `~/.claude/settings.json["env"]` with ISO backup and atomic `0o600` write.
- Delimited block (`# agy:start` ... `# agy:end`) in `~/.codex/config.toml` with ISO backup.
- Model aliasing in `bridge/transform.py` & `bridge/anthropic.py`: map `gemini-3.8-flash-high`, `gemini-3.8-flash`, `auto` to `gemini-3.8-flash-tiered` (HIGH thinking).
- Dashboard snippets in `bridge/dashboard.py`: show native `python3 -m bridge setup-...` commands.

### Out of Scope
- Interactive GUI wizards.
- External dependencies (pure Python 3 stdlib only).
- Config changes outside Claude and Codex config files.

## Capabilities

### New Capabilities
- `client-setup`: Atomic CLI setup commands (`setup-claude`, `setup-codex`) with automated backups.

### Modified Capabilities
- `anthropic-shim`: Alias `gemini-3.8-flash-high`, `gemini-3.8-flash`, and `auto` to `gemini-3.8-flash-tiered` (HIGH thinking).
- `responses-shim`: Alias `gemini-3.8-flash-high`, `gemini-3.8-flash`, and `auto` to `gemini-3.8-flash-tiered` (HIGH thinking).
- `gateway-dashboard`: Point Claude and Codex setup snippets to native CLI subcommands.

## Approach

- Add `bridge/setup.py` with atomic write and ISO backup utilities.
- Wire `setup-claude` and `setup-codex` into `bridge/__main__.py` via `argparse`.
- Add centralized model aliasing in `bridge/transform.py` with `thinkingLevel: "HIGH"`.
- Update `bridge/dashboard.py` cards to display native setup commands.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `bridge/setup.py` | New | Client setup logic and atomic config editing |
| `bridge/__main__.py` | Modified | Add CLI subcommands |
| `bridge/transform.py` | Modified | Model aliasing and thinking level mapping |
| `bridge/anthropic.py` | Modified | Apply aliasing to messages requests |
| `bridge/responses.py` | Modified | Apply aliasing to responses requests |
| `bridge/dashboard.py` | Modified | Update setup card snippets |
| `tests/test_setup.py` | New | Tests for setup CLI, writes, and backups |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Config corruption | Low | Pre-mutation ISO backup + tempfile atomic replacement |
| Clobbering user settings | Low | Surgical JSON key merge and delimited TOML block |

## Rollback Plan

Revert git commit. Restore configs using timestamped `backup-<iso>` snapshots.

## Dependencies

- Python 3 standard library only.

## Success Criteria

- [ ] `setup-claude` updates `~/.claude/settings.json` with backup and `0o600` permissions.
- [ ] `setup-codex` manages `# agy:start` block in `~/.codex/config.toml` with backup.
- [ ] Subcommands are idempotent across invocations.
- [ ] `gemini-3.8-flash-high` and `auto` resolve to `gemini-3.8-flash-tiered` (`thinkingLevel: "HIGH"`).
- [ ] `python3 -m unittest` passes 100%.
