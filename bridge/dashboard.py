"""Embedded dark-mode gateway dashboard and status endpoints.

Zero external dependencies: pure standard library HTML/CSS/JS template.
"""

from typing import Any
import html
import time


_models_cache: dict[str, tuple[float, int]] = {}


def get_status_data(client: Any, project: str, host: str, port: int) -> dict[str, Any]:
    """Inspects token provider and model catalog to return live gateway status data."""
    auth_status: dict[str, Any] = {
        "status": "Missing",
        "email": None,
        "message": "Open Antigravity to refresh",
    }

    token_provider = getattr(client, "token_provider", None)
    if token_provider is not None and hasattr(token_provider, "get_token"):
        try:
            token_provider.get_token()
            raw_account = getattr(token_provider, "account", "antigravity")
            email_str = raw_account if isinstance(raw_account, str) else "antigravity"
            auth_status = {
                "status": "Valid",
                "email": email_str,
                "message": "Authenticated",
            }
            cached_expiry = getattr(token_provider, "_cached_expiry", 0)
            if cached_expiry > 0 and cached_expiry < time.time():
                auth_status["status"] = "Expired"
                auth_status["message"] = "Open Antigravity to refresh"
        except Exception as exc:
            err_text = str(exc).lower()
            if "expired" in err_text:
                status = "Expired"
            else:
                status = "Missing"
            auth_status = {
                "status": status,
                "email": None,
                "message": "Open Antigravity to refresh",
            }

    now = time.time()
    cached_entry = _models_cache.get(project)
    if cached_entry is not None and (now - cached_entry[0] < 60.0):
        models_count = cached_entry[1]
    else:
        models_count = 0
        if client is not None and hasattr(client, "fetch_available_models") and auth_status["status"] == "Valid":
            try:
                models = client.fetch_available_models(project)
                if isinstance(models, list):
                    models_count = len(models)
                    _models_cache[project] = (now, models_count)
            except Exception:
                models_count = cached_entry[1] if cached_entry is not None else 0
                if cached_entry is None:
                    _models_cache[project] = (now - 45.0, 0)

    return {
        "host": host,
        "port": port,
        "address": f"{host}:{port}",
        "auth": auth_status,
        "models_count": models_count,
    }


def render_dashboard(
    host: str,
    port: int,
    auth_status: dict[str, Any],
    models_count: int,
) -> str:
    """Renders the self-contained dark-mode HTML dashboard for the local AI gateway."""
    safe_host = html.escape(str(host))
    safe_port = html.escape(str(port))
    address = f"{safe_host}:{safe_port}"

    snippet_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else safe_host
    snippet_address = f"{snippet_host}:{safe_port}"

    status_name = auth_status.get("status", "Missing")
    email = auth_status.get("email")
    message = auth_status.get("message", "")

    if status_name == "Valid":
        auth_badge_class = "badge-success"
        auth_label = f"Valid ({email})" if email else "Valid"
    elif status_name == "Expired":
        auth_badge_class = "badge-warning"
        auth_label = f"Expired — {message}"
    else:
        auth_badge_class = "badge-danger"
        auth_label = f"Missing — {message}"

    card1_snippet = f"""# OpenAI Chat Completions Endpoint
curl http://{snippet_address}/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer dummy-key" \\
  -d '{{
    "model": "gemini-2.5-pro",
    "messages": [{{"role": "user", "content": "Hello!"}}]
  }}'"""

    card2_snippet = f"""# Claude Code CLI Direct Configuration
export ANTHROPIC_BASE_URL="http://{snippet_address}"
export ANTHROPIC_AUTH_TOKEN="dummy"
# For Gemini/GPT-OSS models (bypasses Claude Code's model picker filter):
export ANTHROPIC_CUSTOM_MODEL_OPTION="gemini-2.5-flash"
# Optional: enable gateway discovery for Claude-family models (v2.1.129+)
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1
claude"""

    card3_snippet = f"""# Codex CLI Configuration (~/.codex/config.toml)
[model]
name = "gemini-2.5-pro"
wire_api = "responses"
base_url = "http://{snippet_address}/v1"

# Hermes / Aider CLI Invocation
aider --openai-api-base http://{snippet_address}/v1 --model gemini-2.5-pro"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AGY Model Bridge — Local AI Gateway</title>
  <style>
    :root {{
      --bg: #000000;
      --card-bg: #111111;
      --card-border: #222222;
      --text-primary: #ededed;
      --text-secondary: #888888;
      --accent: #38bdf8;
      --green: #10b981;
      --green-bg: rgba(16, 185, 129, 0.12);
      --amber: #f59e0b;
      --amber-bg: rgba(245, 158, 11, 0.12);
      --red: #ef4444;
      --red-bg: rgba(239, 68, 68, 0.12);
      --font-sans: Geist, Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }}
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      background-color: var(--bg);
      color: var(--text-primary);
      font-family: var(--font-sans);
      min-height: 100vh;
      padding: 3rem 1.5rem;
      line-height: 1.5;
    }}
    .container {{
      max-width: 900px;
      margin: 0 auto;
    }}
    header {{
      margin-bottom: 2.5rem;
    }}
    h1 {{
      font-size: 1.75rem;
      font-weight: 600;
      letter-spacing: -0.03em;
      margin-bottom: 0.5rem;
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }}
    .subtitle {{
      color: var(--text-secondary);
      font-size: 0.95rem;
    }}
    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-top: 1.5rem;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.8rem;
      font-weight: 500;
      padding: 0.35rem 0.75rem;
      border-radius: 9999px;
      border: 1px solid var(--card-border);
      background: var(--card-bg);
      color: var(--text-primary);
    }}
    .badge-success {{
      border-color: rgba(16, 185, 129, 0.3);
      background: var(--green-bg);
      color: var(--green);
    }}
    .badge-warning {{
      border-color: rgba(245, 158, 11, 0.3);
      background: var(--amber-bg);
      color: var(--amber);
    }}
    .badge-danger {{
      border-color: rgba(239, 68, 68, 0.3);
      background: var(--red-bg);
      color: var(--red);
    }}
    .badge-models {{
      border-color: rgba(56, 189, 248, 0.3);
      background: rgba(56, 189, 248, 0.1);
      color: var(--accent);
    }}
    .cards-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 1.5rem;
      margin-top: 2rem;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 1.25rem 1.5rem;
      position: relative;
    }}
    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.75rem;
    }}
    .card-title {{
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--text-primary);
    }}
    .card-desc {{
      font-size: 0.85rem;
      color: var(--text-secondary);
      margin-bottom: 1rem;
    }}
    .copy-btn {{
      background: #1a1a1a;
      border: 1px solid #333333;
      color: var(--text-primary);
      font-family: var(--font-sans);
      font-size: 0.75rem;
      font-weight: 500;
      padding: 0.35rem 0.75rem;
      border-radius: 6px;
      cursor: pointer;
      transition: background 0.15s ease, border-color 0.15s ease;
    }}
    .copy-btn:hover {{
      background: #262626;
      border-color: #444444;
    }}
    .copy-btn.copied {{
      background: var(--green-bg);
      border-color: var(--green);
      color: var(--green);
    }}
    pre {{
      background: #080808;
      border: 1px solid var(--card-border);
      border-radius: 6px;
      padding: 1rem;
      overflow-x: auto;
      font-family: var(--font-mono);
      font-size: 0.85rem;
      color: #d1d5db;
      line-height: 1.6;
    }}
    footer {{
      margin-top: 3rem;
      border-top: 1px solid var(--card-border);
      padding-top: 1.5rem;
      text-align: center;
      font-size: 0.8rem;
      color: var(--text-secondary);
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>AGY Model Bridge</h1>
      <p class="subtitle">Zero-dependency multi-protocol gateway to Google Cloud Code Assist</p>
      <div class="badges">
        <span class="badge">🌐 {address}</span>
        <span class="badge {auth_badge_class}">🛡️ {html.escape(auth_label)}</span>
        <span class="badge badge-models">⚡ {models_count} Models Discovered</span>
      </div>
    </header>

    <main class="cards-grid">
      <!-- Card 1: FreeLLMAPI Bridge -->
      <section class="card">
        <div class="card-header">
          <h2 class="card-title">FreeLLMAPI Bridge (OpenAI Chat API)</h2>
          <button class="copy-btn" onclick="copySnippet(this, 'snippet-1')">Copy</button>
        </div>
        <p class="card-desc">OpenAI-compatible completions endpoint. Connect NextChat, LibreChat, or the OpenAI Python/TypeScript SDK.</p>
        <pre id="snippet-1"><code>{html.escape(card1_snippet)}</code></pre>
      </section>

      <!-- Card 2: Claude Code Direct -->
      <section class="card">
        <div class="card-header">
          <h2 class="card-title">Claude Code Direct (Anthropic Messages API)</h2>
          <button class="copy-btn" onclick="copySnippet(this, 'snippet-2')">Copy</button>
        </div>
        <p class="card-desc">Native Anthropic Messages shim for Claude Code CLI. Note: Base URL is configured without <code>/v1</code>.</p>
        <pre id="snippet-2"><code>{html.escape(card2_snippet)}</code></pre>
      </section>

      <!-- Card 3: Codex / Hermes / Aider Direct -->
      <section class="card">
        <div class="card-header">
          <h2 class="card-title">Codex / Hermes / Aider Direct (Responses & Chat)</h2>
          <button class="copy-btn" onclick="copySnippet(this, 'snippet-3')">Copy</button>
        </div>
        <p class="card-desc">OpenAI Responses API shim for Codex CLI (<code>wire_api = "responses"</code>) or standard chat completions for Aider/Hermes.</p>
        <pre id="snippet-3"><code>{html.escape(card3_snippet)}</code></pre>
      </section>
    </main>

    <footer>
      <p>AGY Model Bridge &bull; Powered by Google Cloud Code Assist &bull; Local Gateway</p>
    </footer>
  </div>

  <script>
    function copySnippet(btn, elementId) {{
      var el = document.getElementById(elementId);
      if (!el) return;
      var text = el.innerText || el.textContent;

      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(text).then(function() {{
          setCopied(btn);
        }}).catch(function() {{
          fallbackCopy(el, btn);
        }});
      }} else {{
        fallbackCopy(el, btn);
      }}
    }}

    function fallbackCopy(el, btn) {{
      try {{
        var range = document.createRange();
        range.selectNodeContents(el);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        setCopied(btn);
      }} catch (e) {{
        // Selection remains active for manual copy
      }}
    }}

    function setCopied(btn) {{
      var original = btn.innerText;
      btn.innerText = "Copied!";
      btn.classList.add("copied");
      setTimeout(function() {{
        btn.innerText = original;
        btn.classList.remove("copied");
      }}, 2000);
    }}
  </script>
</body>
</html>"""
