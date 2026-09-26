# Client Setup Specification

## Purpose

Provide native CLI setup subcommands (`setup-claude`, `setup-codex`) to surgically configure Claude Code and Codex CLI to connect through the local bridge gateway with automated backups and atomic writes.

## Requirements

### Requirement: Claude Code Settings Configuration (`setup-claude`)

The bridge CLI SHALL provide a `setup-claude` command configuring `~/.claude/settings.json`.
The command MUST load `~/.claude/settings.json` (or initialize `{}`) and merge into `"env"`:
- `ANTHROPIC_BASE_URL`: bridge URL without trailing slash (default: `http://127.0.0.1:8080`).
- `ANTHROPIC_AUTH_TOKEN`: gateway token (default: `"antigravity"`).
- `ANTHROPIC_MODEL`: default model (default: `"gemini-3.8-flash-high"`).
- `ANTHROPIC_DEFAULT_SONNET_MODEL`: sonnet mapping (default: `"gemini-3.8-flash-high"`).
- `ANTHROPIC_DEFAULT_HAIKU_MODEL`: haiku mapping (default: `"gemini-3.8-flash-high"`).
- `ANTHROPIC_DEFAULT_OPUS_MODEL`: opus mapping (default: `"gemini-3.8-flash-high"`).
- `CLAUDE_CODE_AUTO_COMPACT_WINDOW`: compact window (default: `"1048576"`).
- `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY`: model discovery flag (default: `"1"`).

The command MUST preserve all other top-level keys in `settings.json` and pre-existing non-conflicting `"env"` entries.
The command SHALL accept optional CLI flags `--port`, `--model`, and `--url`.

#### Scenario: Setup Claude Code in fresh environment
- GIVEN no existing `~/.claude/settings.json` exists
- WHEN `python3 -m bridge setup-claude` is executed
- THEN `~/.claude/settings.json` is created with mode `0o600`
- AND `"env"` contains required bridge variables pointing to `http://127.0.0.1:8080`.

#### Scenario: Update existing Claude settings preserving user keys
- GIVEN `~/.claude/settings.json` has `{"theme": "dark", "env": {"CUSTOM_KEY": "val"}}`
- WHEN `python3 -m bridge setup-claude` is executed
- THEN a timestamped backup of `settings.json` is created
- AND `theme` and `CUSTOM_KEY` are preserved in the updated file.

#### Scenario: Override port and model via CLI arguments
- GIVEN custom port `9090` and model `gemini-2.5-pro`
- WHEN `python3 -m bridge setup-claude --port 9090 --model gemini-2.5-pro` is executed
- THEN `ANTHROPIC_BASE_URL` is set to `http://127.0.0.1:9090`
- AND `ANTHROPIC_MODEL` is set to `gemini-2.5-pro`.

### Requirement: Codex CLI Delimited Block Configuration (`setup-codex`)

The bridge CLI SHALL provide a `setup-codex` command managing a delimited block in `~/.codex/config.toml`.
The configuration block MUST be enclosed in `# agy:start` and `# agy:end` markers:
```toml
# agy:start
model = "gemini-3.8-flash-high"
model_provider = "agy"
model_context_window = 1048576
model_auto_compact_token_limit = 943718

[model_providers.agy]
name = "agy"
base_url = "http://127.0.0.1:8080/v1"
wire_api = "responses"
# agy:end
```
The command MUST preserve all configuration outside `# agy:start` ... `# agy:end`.
When executed repeatedly, the command MUST replace the delimited block in-place idempotently.
The command SHALL accept optional CLI flags `--port` and `--model`.

#### Scenario: Setup Codex config in fresh environment
- GIVEN no existing `~/.codex/config.toml` exists
- WHEN `python3 -m bridge setup-codex` is executed
- THEN `~/.codex/config.toml` is created with mode `0o600`
- AND contains exactly one `# agy:start` ... `# agy:end` block.

#### Scenario: Replace existing delimited block idempotently
- GIVEN `~/.codex/config.toml` contains existing user tables and a previous agy block
- WHEN `python3 -m bridge setup-codex` is executed
- THEN a timestamped backup of `config.toml` is created
- AND the delimited block is replaced in-place
- AND surrounding user configuration tables remain unchanged.

### Requirement: Safe Atomic File Writing and Timestamped Backups

File modifications performed by setup commands MUST guarantee atomicity and data safety.
Before mutating any existing config file, the tool MUST create an ISO-8601 timestamped backup file in the same directory (`<file>.backup-<timestamp>`).
Modifications MUST be staged to a temporary file in the target directory and atomically moved into place via `os.replace`.
Newly created files MUST have permissions set to `0o600`, and parent directories MUST have permissions set to `0o700`.

#### Scenario: Automated pre-mutation backup
- GIVEN an existing configuration file at the target path
- WHEN a setup subcommand modifies the configuration
- THEN a backup file with suffix `.backup-<ISO8601>` is created with original file contents.

#### Scenario: Atomic replace prevents file corruption
- GIVEN a configuration file update is initiated
- WHEN the write operation writes to a temporary file
- THEN the temporary file is atomically renamed to the target filename
- AND file permissions are set to mode `0o600`.
