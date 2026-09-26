# Tasks: Native Client Setup CLI & Gemini 3.8 Flash High Aliasing

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | ~480-550 lines |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (Aliasing) → PR 2 (Setup Core) → PR 3 (CLI & Dashboard) |
| Delivery strategy | exception-ok |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No (maintainer approved size-exception)
Chain strategy: size-exception
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|---|---|---|---|
| 1 | Model & thinking aliasing | PR 1 | Base: main; transform/anthropic/responses tests (~120 lines) |
| 2 | Atomic write, ISO backup & setup engine | PR 2 | Base: PR 1; tests/test_setup.py included (~280 lines) |
| 3 | CLI subcommands & dashboard cards | PR 3 | Base: PR 2; full regression suite verified (~120 lines) |

## Phase 1: Model & Thinking Aliasing

- [x] 1.1 [RED] Unit tests in `tests/test_transform.py` for `resolve_model_and_thinking()` covering None, "auto", empty, `gemini-3.8-flash-high`, `gemini-3.8-flash`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-low`, and explicit `thinkingConfig`.
- [x] 1.2 [GREEN] Implement `resolve_model_and_thinking()` in `bridge/transform.py`; integrate into `anthropic_to_cloudcode_request()` and `responses_to_cloudcode_request()`.
- [x] 1.3 [REFACTOR] Clean up model aliasing logic; update `tests/test_anthropic.py` & `tests/test_responses.py` for aliased/omitted models.

## Phase 2: Atomic File Write & ISO-8601 Backup Utilities

- [x] 2.1 [RED] Unit tests in `tests/test_setup.py` for `atomic_write_file()` (mode `0o600`, parent dir `0o700`, atomic replacement) and `create_backup()` (timestamped filename, content preservation).
- [x] 2.2 [GREEN] Implement `atomic_write_file()` and `create_backup()` in `bridge/setup.py`.
- [x] 2.3 [REFACTOR] Streamline error handling, tempfile cleanup, and permission management in `bridge/setup.py`.

## Phase 3: Claude Code Surgical Setup

- [x] 3.1 [RED] Unit tests in `tests/test_setup.py` for `setup_claude()`: fresh creation, surgical merge of `env` keys, preservation of top-level keys and custom `env` entries, CLI flags (`--port`, `--model`, `--url`).
- [x] 3.2 [GREEN] Implement `setup_claude()` in `bridge/setup.py`.
- [x] 3.3 [REFACTOR] Standardize JSON formatting (2 spaces indentation) and idempotency across repeated runs.

## Phase 4: Codex CLI Delimited Block Setup

- [x] 4.1 [RED] Unit tests in `tests/test_setup.py` for `setup_codex()`: fresh config, insertion/replacement of delimited `# agy:start` ... `# agy:end` block, pre-existing table preservation, CLI flags.
- [x] 4.2 [GREEN] Implement `setup_codex()` in `bridge/setup.py`.
- [x] 4.3 [REFACTOR] Refactor regex delimited block matching and TOML section handling.

## Phase 5: CLI Subcommand Integration

- [x] 5.1 [RED] Unit tests in `tests/test_setup.py` for CLI parsing in `bridge/__main__.py` for daemon mode and `setup-claude` / `setup-codex` subcommands.
- [x] 5.2 [GREEN] Implement dual-mode `argparse` in `bridge/__main__.py` wiring subcommands to `setup_claude()` and `setup_codex()`.
- [x] 5.3 [REFACTOR] Polish CLI help messages, exit codes, and stdout feedback.

## Phase 6: Dashboard Setup Cards & Full Verification

- [x] 6.1 Update `CLIENT_CARDS` in `bridge/dashboard.py` to display `python3 -m bridge setup-claude` and `python3 -m bridge setup-codex` with tests in `tests/test_dashboard.py`.
- [x] 6.2 Full regression test: run `python3 -m unittest discover tests -v` verifying all existing and new tests pass.
