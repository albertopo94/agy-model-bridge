# Feature Tasks: Gemini 4 Argon & AGY 1.4.0 Upstream Support

## Context
Following the update of Actigravity CLI (`agy`) from 1.3.6 to 1.4.0, Google Cloud Code Assist (`daily-cloudcode-pa.googleapis.com`) now offers Gemini 4 Argon (`gemini-4-argon-high`, `gemini-4-argon-medium`, `gemini-4-argon-low`) with deep thinking support and separate quota allocation. Google strictly gates Argon access behind modern client `User-Agent` strings. This feature updates the bridge upstream client, model routing table, client setup scripts, and dashboard to fully support Gemini 4 Argon.

## Tasks

### 1. Upstream Client Modernization (User-Agent)
- [ ] 1.1 Update `User-Agent` in `bridge/client.py` to match `antigravity/cli/1.4.0` format so Google does not return 404 for Argon and discovers all 29 models.
- [ ] 1.2 Update tests in `tests/test_client.py` to assert the modern User-Agent header is sent.

### 2. Model Routing & Thinking Level Mapping (TDD)
- [ ] 2.1 [RED] Add unit tests in `tests/test_transform.py` asserting `gemini-4-argon`, `gemini-4-argon-high`, `gemini-4-argon-medium`, `gemini-4-argon-low` and `argon-*` aliases resolve to correct upstream model IDs and thinking levels (`HIGH`, `MEDIUM`, `LOW`).
- [ ] 2.2 [GREEN] Update `MODEL_TIER_TABLE` in `bridge/transform.py` to map Argon models and aliases.

### 3. Client Environment Setups
- [ ] 3.1 Update `bridge/setup/pi_gentle.py` to include `gemini-4-argon-high`, `gemini-4-argon-medium`, and `gemini-4-argon-low` in `DEFAULT_PI_AND_GENTLE_MODELS` with 1M context, 64k max output, and reasoning capabilities.
- [ ] 3.2 Update `bridge/setup/opencode.py`, `bridge/setup/claude.py`, `bridge/setup/codex.py`, and `bridge/setup/cursor.py` to register Argon models.

### 4. Dashboard & Quota Translations
- [ ] 4.1 Update `bridge/dashboard.py` quick-setup cards, model chips, and quota bucket translations for `Gemini 4 Argon Weekly Limit`.

### 5. Verification & Full Test Suite
- [ ] 5.1 Run pytest across the entire repository to ensure 100% pass rate.
- [ ] 5.2 Test live model listing (`/v1/models`) and test execution with `gemini-4-argon-high`.
