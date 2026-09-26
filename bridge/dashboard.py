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
                _models_cache[project] = (now - 45.0, models_count)

    return {
        "host": host,
        "port": port,
        "address": f"{host}:{port}",
        "auth": auth_status,
        "models_count": models_count,
    }


CLIENT_CARDS: list[dict[str, Any]] = [
    {
        "id": "claude",
        "title": "Claude Code",
        "desc": "Anthropic Messages API CLI (Base URL without /v1)",
        "auto_cmd": lambda addr: (
            f'export ANTHROPIC_BASE_URL="http://{addr}" '
            f'ANTHROPIC_AUTH_TOKEN="local-bridge" '
            f'ANTHROPIC_CUSTOM_MODEL_OPTION="gemini-2.5-flash" '
            f'CLAUDE_CODE_USE_GATEWAY=1 && claude'
        ),
        "manual_snippet": lambda addr: f'export ANTHROPIC_BASE_URL="http://{addr}"\nexport ANTHROPIC_AUTH_TOKEN="local-bridge"',
        "docs_url": "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview",
    },
    {
        "id": "codex",
        "title": "Codex CLI",
        "desc": "OpenAI Responses API CLI (wire_api = 'responses')",
        "auto_cmd": lambda addr: (
            f'mkdir -p ~/.codex && printf \'\\n[model]\\nwire_api = "responses"\\nbase_url = "http://{addr}/v1"\\n\' >> ~/.codex/config.toml'
        ),
        "manual_snippet": lambda addr: f'# ~/.codex/config.toml\n[model]\nwire_api = "responses"\nbase_url = "http://{addr}/v1"',
        "docs_url": "https://github.com/openai/codex",
    },
    {
        "id": "hermes",
        "title": "Hermes Agent",
        "desc": "NousResearch Hermes Agent CLI (Base URL with /v1)",
        "auto_cmd": lambda addr: f'export OPENAI_BASE_URL="http://{addr}/v1" OPENAI_API_KEY="local-bridge" && hermes',
        "manual_snippet": lambda addr: f'export OPENAI_BASE_URL="http://{addr}/v1"\nexport OPENAI_API_KEY="local-bridge"',
        "docs_url": "https://hermes-agent.nousresearch.com",
    },
    {
        "id": "freellmapi",
        "title": "FreeLLMAPI",
        "desc": "Custom Provider & Aider integration (Base URL with /v1)",
        "auto_cmd": lambda addr: f"http://{addr}/v1",
        "manual_snippet": lambda addr: f'BASE_URL=http://{addr}/v1\nAPI_KEY=local-bridge',
        "docs_url": "https://github.com/tashfeenahmed/freellmapi",
    },
]


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

    cards_html_parts: list[str] = []
    for card in CLIENT_CARDS:
        auto_text = card["auto_cmd"](snippet_address)
        manual_text = card["manual_snippet"](snippet_address)
        card_id = card["id"]
        cards_html_parts.append(f"""      <section class="card">
        <div class="card-header">
          <h2 class="card-title">{html.escape(card["title"])}</h2>
        </div>
        <p class="card-desc">{html.escape(card["desc"])}</p>

        <div class="setup-block">
          <div class="setup-header">
            <span class="setup-title">Configuración automática</span>
            <button class="copy-btn" onclick="copySnippet(this, '{card_id}-auto')">Copy</button>
          </div>
          <pre id="{card_id}-auto"><code>{html.escape(auto_text)}</code></pre>
        </div>

        <div class="setup-block">
          <div class="setup-header">
            <span class="setup-title">Conexión manual</span>
            <button class="copy-btn" onclick="copySnippet(this, '{card_id}-manual')">Copy</button>
          </div>
          <pre id="{card_id}-manual"><code>{html.escape(manual_text)}</code></pre>
        </div>

        <div class="card-footer">
          <a href="{html.escape(card["docs_url"])}" target="_blank" rel="noopener noreferrer" class="docs-link">Documentación ↗</a>
        </div>
      </section>""")
    cards_html = "\n".join(cards_html_parts)

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
      max-width: 960px;
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
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1.5rem;
      margin-top: 2rem;
    }}
    @media (max-width: 768px) {{
      .cards-grid {{
        grid-template-columns: 1fr;
      }}
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 1.25rem 1.5rem;
      position: relative;
      display: flex;
      flex-direction: column;
    }}
    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.5rem;
    }}
    .card-title {{
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--text-primary);
    }}
    .card-desc {{
      font-size: 0.85rem;
      color: var(--text-secondary);
      margin-bottom: 0.75rem;
    }}
    .setup-block {{
      margin-top: 0.75rem;
    }}
    .setup-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.35rem;
    }}
    .setup-title {{
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-secondary);
    }}
    .card-footer {{
      margin-top: auto;
      padding-top: 1rem;
      border-top: 1px solid var(--card-border);
      display: flex;
      justify-content: flex-end;
    }}
    .docs-link {{
      color: var(--accent);
      font-size: 0.8rem;
      text-decoration: none;
      transition: color 0.15s ease;
    }}
    .docs-link:hover {{
      text-decoration: underline;
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
      padding: 0.75rem 1rem;
      overflow-x: auto;
      font-family: var(--font-mono);
      font-size: 0.82rem;
      color: #d1d5db;
      line-height: 1.5;
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
{cards_html}
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
        var successful = document.execCommand('copy');
        window.getSelection().removeAllRanges();
        if (successful) {{
          setCopied(btn);
        }}
      }} catch (e) {{
        // Selection remains active for manual copy
      }}
    }}

    function setCopied(btn) {{
      if (btn.classList.contains("copied")) return;
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
