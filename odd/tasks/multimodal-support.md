# Feature: Multimodal Image Support
End-to-end multimodal image support across OpenAI, Anthropic, and Responses APIs into Antigravity and Cursor upstreams.

## Specs
- **S1** (user verbatim): "Error: 400: {\"message\":\"Multimodal image content is not supported by agy-model-bridge\",\"type\":\"invalid_request_error\",\"code\":400}" -> Remove hardcoded rejection of multimodal images and translate them into upstream representation.
- **S2**: In `bridge/transform.py` (OpenAI chat completions), `bridge/anthropic.py` (Anthropic messages), and `bridge/responses.py` (Codex responses), parse multimodal image parts (`image_url` data URIs, Anthropic `{"type": "image", "source": {"type": "base64", "media_type", "data"}}`, and Codex `input_image`) and map them to Google Cloud Code Assist `inlineData: {"mimeType": str, "data": str}` within the turn's `parts` list, alongside existing text parts.
- **S3**: In `bridge/cursor_backend.py` and `bridge/cursor_acp.py`, preserve image content in ACP prompt submissions and text representations rather than discarding them.
- **S4**: In `bridge/setup/pi_gentle.py` and `bridge/setup/openclaw.py`, update model definitions to declare `"input": ["text", "image"]` for vision-capable models (Gemini, Claude Sonnet/Opus, Cursor models).
- **S5**: Update tests (replace rejection tests with conversion tests, add end-to-end format tests), update README test count, and bump version to v0.36.0.

## Tasks
- [x] **T1** (S1, S2): OpenAI chat completions multimodal image parser and translation to `inlineData` in `bridge/transform.py`. Route: inline. Commit: 998e49f.
- [x] **T2** (S1, S2): Anthropic messages and Responses API multimodal image translation in `bridge/anthropic.py` and `bridge/responses.py`. Route: inline. Commit: dfd38eb.
- [x] **T3** (S3): Cursor ACP and backend multimodal content preservation in `bridge/cursor_backend.py` and `bridge/cursor_acp.py`. Route: inline. Commit: dc219e7.
- [x] **T4** (S4): Client configurators (`pi_gentle.py`, `openclaw.py`) updating vision-capable models to `"input": ["text", "image"]`. Route: inline. Commit: 81d0937.
- [x] **T5** (S5): Documentation, test suite verification, test count synchronization, and SemVer bump to v0.36.0. Route: inline. Commit: 4334d48.

> **Slice boundary**: All 5 tasks complete across 5 commits on feature/multimodal-support. 1,165 tests passing (100% pass rate). Ready for merge to main.

## Log
- **L1**: User reported 400 rejection when sending screenshot from Gentle Shell using claude-opus-5-5-high.
- **L2**: Empirically proved via live API probe that Google Cloud Code Assist natively supports `inlineData` for Gemini and Claude models (answered "Solid black pixel" and "Blank white pixel").
- **L3**: User confirmed expanding multimodal vision across Antigravity and Cursor models without dropping text capabilities.
