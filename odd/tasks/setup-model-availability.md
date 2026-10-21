# Feature Tasks: Accurate AGY Model Presets in Client Setup

## Context
The `agy-bridge setup-*` commands write a hard-coded model list into each client's
config (`~/.pi/agent/models.json`, `opencode.json`, `openclaw.json`, ...). Two
problems found while debugging why `claude-*` and `gemini-4-argon-*` did not answer
in Gentle Shell:

1. The AGY (Antigravity) preset lists advertise `claude-haiku-5-5-{high,medium,low}`,
   but the account catalog from `fetchAvailableModels` does not serve Haiku on the
   free tier, so those picker entries always fail with upstream 404.
2. The write path never checks the live catalog, so any model Google does not serve
   for the account still gets written into the client config. `/v1/models` already
   reflects reality because it calls `fetch_available_models`; presets do not.

## Specs
- S1 (user, verbatim): "2. si debemos sacar haiku de los modelos que brinda el backen de agy."
  → Remove `claude-haiku-5-5-high`, `claude-haiku-5-5-medium` and `claude-haiku-5-5-low`
  from the Antigravity/AGY model presets written by the setup commands.
- S2 (user, verbatim): "3. no suena mal." — approving the proposal:
  "`setup-pi` ... escribe `models.json`, primero pide `fetchAvailableModels` y escribe
  sólo los modelos que tu cuenta realmente puede servir, avisando cuáles filtró:
  _3 preset models not available for your plan and were skipped: claude-haiku-5-5-high, …_"
  → Catalog discovery runs before writing; models the account cannot serve are skipped
  with one notice listing them; models the account serves that the preset omits are
  still written. When the catalog cannot be reached there is no filtering and no
  error: the preset list is written as today, plus a notice that availability could
  not be verified.
- S3 (user, verbatim): "entiendo lo que dices del backend de Cursor, me referia a los
  de antigravity (agy)." → Cursor entries stay untouched, including
  `cursor/claude-haiku-5-5-high`. Only AGY/antigravity presets change.
- S4: Existing behaviour that must not change: `--provider agy|cursor|all` selection,
  the configured default model, atomic writes with `0o600` permissions, timestamped
  backups, and `restore-*` round-trip.

## Tasks
- T1 — Route: inline. Remove the three AGY Haiku entries from
  `bridge/setup/pi_gentle.py` (DEFAULT_PI_AND_GENTLE_MODELS), `bridge/setup/opencode.py`
  and `bridge/setup/openclaw.py`; update the setup tests that assert the model list.
  Specs: S1, S3. Commit: fix(setup).
- T2 — Route: inline. Add a shared availability helper that queries
  `CloudCodeClient.fetch_available_models` defensively and returns the filter set plus
  the skipped/added ids; wire it into the AGY branch of the setup write path so only
  servable models are written and skipped ids are reported. Specs: S2, S4. Commit: feat(setup).
- T3 — Route: inline. i18n strings (English + Spanish) for the skipped-models notice
  and the could-not-verify notice; surface them in the setup output. Specs: S2. Commit: feat(setup).
- T4 — Route: inline. Docs: README preset lists and setup notes that mention
  `claude-haiku-5-5-*` under AGY. Specs: S1. Commit: docs.
- T5 — Route: inline. Verify: full unit suite, plus one live `setup-pi` run against an
  isolated HOME asserting Haiku is absent, Argon is present, the Cursor block is
  untouched, and the notice is printed. Specs: S1-S4. Commit: (no source change).

## Log
- L1 (user, verbatim): "por que cuando intento usar el producto que hemos creado en este repo solo me funciona si uso los modelos de gemini-* pero no si intento usar el modelo argon-* o claude-* ?? ahora ya se me acabo la cuota de gemini-* y quiero usar los otros modelos que te dije que no puedo."
- L2: Root cause of L1 found and fixed in commit e069fbe — `MODEL_TIER_TABLE` collapsed
  `claude-*-5-5-{high,medium,low}` onto bare ids that do not exist upstream (404).
  Live evidence after fix: sonnet/opus all tiers OK, argon OK, `gpt-oss-120b-medium` OK.
- L3 (user, verbatim): "entiendo lo que dices del backend de Cursor, me referia a los de
  antigravity (agy). lo de haiku te lo acepto, pero me estas diciendo que antes de tus
  modificaciones los modelos argon-* y claude-* (opus y sonnet) del backend de agy estaban
  funcionando? por que yo los intente usar en gentle-shell y no me respondian."
- L4: Gentle Shell session logs
  (`~/.gentle-shell/agent/sessions/--Users-albertmac11-Reguero-Proyectos-youtube--/2026-10-18T18-09-45-832Z_01a15034-*.jsonl`)
  show: `claude-opus-5-5-medium` → 404 x2, `claude-sonnet-5-5-high` → 404 x1 (never
  worked); `gemini-4-argon-low` → stop 4.6s on 2026-10-16 (worked); `gemini-4-argon-medium`
  → "aborted" 23.3s 0 tokens on 2026-10-19 right after seven consecutive Gemini 429s
  (client-side abort, not a bridge rejection); `gemini-3.8-flash-high` → ~1280 successes
  until quota exhausted. Conclusion: Argon was already routed correctly; Claude was not.
- L5: Measured time-to-first-token with ~6k token context: argon-medium 5.9s,
  argon-low 14.8s, claude-sonnet-5-5-high 4.3s. Argon is not hanging; low tier is slow.
- L6: Slice boundaries on feat/gemini-4-argon (reviewable units): e069fbe
  fix(transform) Claude 5.5 tiered ids; 0802f77 fix(setup) drop AGY Haiku presets;
  a90a268 fix(setup) drop dead gemini-3.7-flash-tiered picker entry; 4d29bae
  feat(setup) availability filter in configurators+helpers (~303 authored lines);
  next commit closes the feature with the CLI wiring + i18n notices + README
  (~225 authored lines). Each unit stays under ~400 lines; the branch total only
  grows because it carries four independent work units.
- L7: Verification evidence: python3 -m unittest discover -s tests → 1044 run,
  OK (configurators, CLI handlers, i18n both locales, availability helper).
  Live catalog cross-check: every id written to a filtered config exists in
  fetchAvailableModels; gemini-3.7-flash-tiered probed 404 live before removal.
  Incident during an availability test run: handle_setup_pi writes to the real
  Gentle Shell path when --path is omitted regardless of $HOME; the single run
  was restored from its own backup (restore_pi → byte-identical 283956 bytes).
- L8: Feature closed. T1-T6 done; final unit 5ec6648. Live post-restart check: claude-sonnet-5-5-high, claude-opus-5-5-medium, argon all OK through /v1/chat/completions.
- L9 (T7): Live E2E of the new filter exposed a false skip: preset id
  "gemini-3.8" is a bridge alias, not an upstream id; MODEL_TIER_TABLE resolves
  it to gemini-3.8-flash-tiered, which the catalog does serve. Fix:
  fetch_agy_available_models now expands the catalog with with_bridge_aliases
  (alias kept when its resolved target is in the catalog). Re-run live: 13 AGY
  models written, gemini-3.8 present, haiku absent, notice silent. Suite 1048 OK,
  ruff/mypy clean against CI (.github/workflows/ci.yml runs the same commands).
