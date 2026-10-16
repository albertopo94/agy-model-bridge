# Feature Tasks: Gemini 4 Argon & AGY 1.4.0 Upstream Support

## Context
Following the update of Actigravity CLI (`agy`) from 1.3.6 to 1.4.0, Google Cloud Code Assist (`daily-cloudcode-pa.googleapis.com`) now offers Gemini 4 Argon (`gemini-4-argon-high`, `gemini-4-argon-medium`, `gemini-4-argon-low`) with deep thinking support and separate quota allocation. Google strictly gates Argon access behind modern client `User-Agent` strings. This feature updates the bridge upstream client, model routing table, client setup scripts, and dashboard to fully support Gemini 4 Argon.

## Tasks

### 1. Upstream Client Modernization (User-Agent)
- [x] 1.1 Update `User-Agent` in `bridge/client.py` to match `antigravity/cli/1.4.0` format so Google does not return 404 for Argon and discovers all 29 models.
- [x] 1.2 Update tests in `tests/test_client.py` to assert the modern User-Agent header is sent.
  - Evidence: Commit 1336f82, 24 client tests passing.

### 2. Model Routing & Thinking Level Mapping (TDD)
- [x] 2.1 [RED] Add unit tests in `tests/test_transform.py` asserting `gemini-4-argon`, `gemini-4-argon-high`, `gemini-4-argon-medium`, `gemini-4-argon-low` and `argon-*` aliases resolve to correct upstream model IDs and thinking levels (`HIGH`, `MEDIUM`, `LOW`).
- [x] 2.2 [GREEN] Update `MODEL_TIER_TABLE` in `bridge/transform.py` to map Argon models and aliases.
  - Evidence: Commit 33ad041, 165 transform tests passing.

### 3. Client Environment Setups
- [x] 3.1 Update `bridge/setup/pi_gentle.py` to include `gemini-4-argon-high`, `gemini-4-argon-medium`, and `gemini-4-argon-low` in `DEFAULT_PI_AND_GENTLE_MODELS` with 1M context, 64k max output, and reasoning capabilities.
- [x] 3.2 Update `bridge/setup/opencode.py`, `bridge/setup/claude.py`, `bridge/setup/codex.py`, and `bridge/setup/cursor.py` to register Argon models.
  - Evidence: Commit c982e82, 293 setup tests passing.

### 4. Dashboard & Quota Translations
- [x] 4.1 Update `bridge/dashboard.py` quick-setup cards, model chips, and quota bucket translations for `Gemini 4 Argon Weekly Limit`.
  - Evidence: Commit 3884f39, 35 dashboard tests and 20 quota tests passing.

### 5. Verification & Full Test Suite
- [x] 5.1 Run pytest across the entire repository to ensure 100% pass rate.
  - Evidence: 1020 tests passing in 43s.
- [x] 5.2 Test live model listing (`/v1/models`) and test execution with `gemini-4-argon-high`.
  - Evidence: Live streaming verified with Keychain token against daily-cloudcode-pa.googleapis.com for gemini-4-argon-high, gemini-4-argon-medium, and gemini-4-argon alias.
