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


CLAUDE_ICON_SVG = (
    '<svg class="card-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="24" height="24" aria-hidden="true">'
    '<rect width="3" height="12" x="22.5" y="-4.5" fill="#ffc400" transform="rotate(90 24 1.5)"/>'
    '<rect width="3" height="3" x="36" y="6" fill="#ffc400" transform="rotate(90 37.5 7.5)"/>'
    '<rect width="3" height="6" x="31.5" y="1.5" fill="#ffc400" transform="rotate(90 33 4.5)"/>'
    '<rect width="3" height="3" x="9" y="6" fill="#ffc400" transform="rotate(90 10.5 7.5)"/>'
    '<rect width="3" height="6" x="13.5" y="1.5" fill="#ffc400" transform="rotate(90 15 4.5)"/>'
    '<rect width="3" height="12" x="22.5" y="7.5" fill="#ffc400" transform="rotate(-90 24 13.5)"/>'
    '<rect width="3" height="6" x="13.5" y="7.5" fill="#ffc400" transform="rotate(-90 15 10.5)"/>'
    '<rect width="3" height="6" x="31.5" y="7.5" fill="#ffc400" transform="rotate(-90 33 10.5)"/>'
    '<rect width="36" height="24" x="6" y="18" fill="#d77757"/>'
    '<rect width="3" height="9" x="9" y="39" fill="#d77757"/>'
    '<rect width="3" height="9" x="15" y="39" fill="#d77757"/>'
    '<rect width="3" height="9" x="30" y="39" fill="#d77757"/>'
    '<rect width="3" height="9" x="36" y="39" fill="#d77757"/>'
    '<rect width="7.5" height="6" y="33" fill="#d77757"/>'
    '<rect width="7.5" height="6" x="40.5" y="33" fill="#d77757"/>'
    '<rect width="3" height="6" x="12" y="24" fill="#111111"/>'
    '<rect width="3" height="6" x="33" y="24" fill="#111111"/>'
    '</svg>'
)

CODEX_ICON_SVG = (
    '<svg class="card-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 270.35 270.35" width="24" height="24" aria-hidden="true">'
    '<defs>'
    '<linearGradient id="codex-linear-gradient" x1="24.95" x2="245.4" y1="135.17" y2="135.17" gradientUnits="userSpaceOnUse">'
    '<stop offset="0" stop-color="#f9f9f9"/>'
    '<stop offset="1" stop-color="#fff"/>'
    '</linearGradient>'
    '</defs>'
    '<g id="Layer_1-2">'
    '<rect width="270.35" height="270.35" rx="53.01" ry="53.01" fill="#181818"/>'
    '<path d="M151.67,244.42c-7.28,0-14.2-1.38-20.76-4.15-6.55-2.77-12.38-6.63-17.48-11.58-5.53,1.89-11.29,2.84-17.26,2.84-9.76,0-18.79-2.4-27.09-7.21-8.3-4.81-15-11.36-20.1-19.66-4.95-8.3-7.43-17.55-7.43-27.75,0-4.22.58-8.81,1.75-13.76-5.83-5.39-10.34-11.58-13.55-18.57-3.2-7.14-4.81-14.57-4.81-22.29s1.68-15.44,5.03-22.72c3.35-7.28,8.01-13.55,13.98-18.79,6.12-5.39,13.18-9.1,21.19-11.14,1.6-8.3,4.95-15.73,10.05-22.29,5.24-6.7,11.65-11.94,19.23-15.73,7.57-3.79,15.66-5.68,24.25-5.68,7.28,0,14.2,1.38,20.76,4.15,6.55,2.77,12.38,6.63,17.48,11.58,5.53-1.89,11.29-2.84,17.26-2.84,9.76,0,18.79,2.4,27.09,7.21,8.3,4.81,14.93,11.36,19.88,19.66,5.1,8.3,7.65,17.55,7.65,27.75,0,4.22-.58,8.81-1.75,13.76,5.83,5.39,10.34,11.65,13.55,18.79,3.2,6.99,4.81,14.35,4.81,22.07s-1.68,15.44-5.03,22.72c-3.35,7.28-8.08,13.62-14.2,19.01-5.97,5.24-12.96,8.89-20.97,10.92-1.6,8.3-5.03,15.73-10.27,22.29-5.1,6.7-11.43,11.94-19.01,15.73-7.57,3.79-15.66,5.68-24.25,5.68ZM97.7,217.11c7.28,0,13.62-1.53,19.01-4.59l41.08-23.6c1.46-1.02,2.18-2.4,2.18-4.15v-18.79l-52.87,30.37c-3.2,1.89-6.41,1.89-9.61,0l-41.29-23.81c0,.44-.07.95-.22,1.53v2.62c0,7.43,1.75,14.27,5.24,20.54,3.64,6.12,8.67,10.92,15.08,14.42,6.41,3.64,13.55,5.46,21.41,5.46ZM99.89,181.49c.87.44,1.68.66,2.4.66s1.46-.22,2.18-.66l16.39-9.39-52.66-30.59c-3.2-1.89-4.81-4.73-4.81-8.52v-47.41c-7.28,3.2-13.11,8.16-17.48,14.86-4.37,6.55-6.55,13.84-6.55,21.85,0,7.14,1.82,13.98,5.46,20.54,3.64,6.55,8.38,11.51,14.2,14.86l40.86,23.81ZM151.67,230c7.72,0,14.71-1.75,20.97-5.24,6.26-3.5,11.22-8.3,14.86-14.42,3.64-6.12,5.46-12.96,5.46-20.54v-47.19c0-1.75-.73-3.06-2.18-3.93l-16.6-9.61v60.96c0,3.79-1.6,6.63-4.81,8.52l-41.29,23.81c7.14,5.1,15,7.65,23.6,7.65ZM159.97,150.03v-29.71l-24.69-13.98-24.91,13.98v29.71l24.91,13.98,24.69-13.98ZM96.17,80.33c0-3.79,1.6-6.63,4.81-8.52l41.29-23.81c-7.14-5.1-15-7.65-23.6-7.65-7.72,0-14.71,1.75-20.97,5.24-6.26,3.5-11.22,8.3-14.86,14.42-3.5,6.12-5.24,12.96-5.24,20.54v46.97c0,1.75.73,3.13,2.18,4.15l16.39,9.61v-60.96ZM207.16,184.77c7.28-3.2,13.04-8.16,17.26-14.86,4.37-6.7,6.55-13.98,6.55-21.85,0-7.14-1.82-13.98-5.46-20.54-3.64-6.55-8.38-11.51-14.2-14.86l-40.86-23.6c-.87-.58-1.68-.8-2.4-.66-.73,0-1.46.22-2.18.66l-16.39,9.18,52.87,30.81c1.6.87,2.77,2.04,3.5,3.5.87,1.31,1.31,2.91,1.31,4.81v47.41ZM163.25,73.78c3.2-2.04,6.41-2.04,9.61,0l41.51,24.25v-3.93c0-6.99-1.75-13.62-5.24-19.88-3.35-6.41-8.23-11.51-14.64-15.29-6.26-3.79-13.55-5.68-21.85-5.68-7.28,0-13.62,1.53-19.01,4.59l-41.08,23.6c-1.46,1.02-2.18,2.4-2.18,4.15v18.79l52.87-30.59Z" fill="url(#codex-linear-gradient)"/>'
    '</g>'
    '</svg>'
)

GITHUB_ICON_SVG = (
    '<svg class="github-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 135 48" aria-hidden="true">'
    '<path fill="currentColor" fill-rule="evenodd" d="M17.43 5C7.79992 5 0 12.7999 0 22.43C0 30.1428 4.98934 36.6572 11.9178 38.9667C12.7893 39.1192 13.1161 38.5963 13.1161 38.1388C13.1161 37.7248 13.0943 36.3522 13.0943 34.8924C8.715 35.6986 7.58205 33.8249 7.23345 32.8444C7.03736 32.3433 6.18765 30.7964 5.44687 30.3824C4.83682 30.0556 3.96532 29.2495 5.42509 29.2277C6.7977 29.2059 7.77814 30.4914 8.10495 31.0143C9.67365 33.6506 12.1792 32.9098 13.1814 32.4522C13.3339 31.3193 13.7915 30.5567 14.2926 30.121C10.4144 29.6852 6.36195 28.1819 6.36195 21.5149C6.36195 19.6194 7.03736 18.0507 8.14852 16.8306C7.97422 16.3949 7.36417 14.6083 8.32282 12.2117C8.32282 12.2117 9.78259 11.7541 13.1161 13.9982C14.5105 13.6061 15.992 13.41 17.4736 13.41C18.9551 13.41 20.4367 13.6061 21.8311 13.9982C25.1646 11.7323 26.6243 12.2117 26.6243 12.2117C27.583 14.6083 26.9729 16.3949 26.7986 16.8306C27.9098 18.0507 28.5852 19.5976 28.5852 21.5149C28.5852 28.2037 24.5109 29.6852 20.6328 30.121C21.2646 30.6657 21.8093 31.7115 21.8093 33.3455C21.8093 35.6768 21.7875 37.5505 21.7875 38.1388C21.7875 38.5963 22.1143 39.141 22.9858 38.9667C26.446 37.7986 29.4527 35.5748 31.5828 32.6083C33.7129 29.6418 34.8591 26.082 34.86 22.43C34.86 12.7999 27.0601 5 17.43 5Z" clip-rule="evenodd"/>'
    '<path fill="currentColor" d="M81.2557 30.843H81.2151C81.2334 30.843 81.2456 30.8633 81.2639 30.8654H81.2761L81.2557 30.845V30.843ZM81.2639 30.8654C81.0748 30.8674 80.5989 30.9671 80.0966 30.9671C78.5105 30.9671 77.9615 30.235 77.9615 29.2793V22.9124H81.1947C81.3777 22.9124 81.5201 22.7497 81.5201 22.526V19.0691C81.5201 18.886 81.3574 18.7234 81.1947 18.7234H77.9615V14.4327C77.9615 14.27 77.8598 14.1683 77.6768 14.1683H73.2844C73.1014 14.1683 72.9997 14.27 72.9997 14.4327V18.8454C72.9997 18.8454 70.7832 19.3944 70.6409 19.4147C70.4782 19.4554 70.3765 19.5978 70.3765 19.7604V22.526C70.3765 22.7497 70.5392 22.9124 70.7222 22.9124H72.9794V29.5822C72.9794 34.544 76.4363 35.0524 78.7952 35.0524C79.873 35.0524 81.1744 34.7067 81.3777 34.605C81.4998 34.5643 81.5608 34.422 81.5608 34.2796V31.2294C81.5636 31.1429 81.5351 31.0582 81.4806 30.991C81.426 30.9238 81.3491 30.8785 81.2639 30.8633V30.8654ZM129.45 26.3897C129.45 22.709 127.965 22.221 126.399 22.3837C125.179 22.465 124.203 23.075 124.203 23.075V30.233C124.203 30.233 125.2 30.9244 126.684 30.965C128.779 31.026 129.45 30.2736 129.45 26.3897ZM134.391 26.0643C134.391 33.0392 132.134 35.032 128.189 35.032C124.854 35.032 123.064 33.3442 123.064 33.3442C123.064 33.3442 122.983 34.2796 122.881 34.4016C122.82 34.5236 122.719 34.5643 122.597 34.5643H119.587C119.384 34.5643 119.201 34.4016 119.201 34.2186L119.242 11.6264C119.242 11.4434 119.404 11.2808 119.587 11.2808H123.919C124.102 11.2808 124.264 11.4434 124.264 11.6264V19.2927C124.264 19.2927 125.932 18.215 128.372 18.215L128.352 18.1743C130.792 18.1743 134.391 19.0894 134.391 26.0643ZM116.659 18.7234H112.389C112.165 18.7234 112.043 18.886 112.043 19.1097V30.172C112.043 30.172 110.924 30.965 109.399 30.965C107.874 30.965 107.427 30.2736 107.427 28.7485V19.0894C107.427 18.9064 107.264 18.7437 107.081 18.7437H102.729C102.546 18.7437 102.384 18.9064 102.384 19.0894V29.4806C102.384 33.9543 104.885 35.0727 108.322 35.0727C111.148 35.0727 113.446 33.5069 113.446 33.5069C113.446 33.5069 113.548 34.3 113.609 34.422C113.649 34.5236 113.792 34.605 113.934 34.605H116.659C116.883 34.605 117.005 34.4423 117.005 34.2593L117.045 19.0691C117.045 18.886 116.883 18.7234 116.659 18.7234ZM68.465 18.703H64.1337C63.9507 18.703 63.788 18.886 63.788 19.1097V34.0356C63.788 34.4423 64.0523 34.5847 64.398 34.5847H68.3023C68.709 34.5847 68.8107 34.4016 68.8107 34.0356V19.0487C68.8107 18.8657 68.648 18.703 68.465 18.703ZM66.3298 11.8298C64.7641 11.8298 63.5236 13.0702 63.5236 14.636C63.5236 16.2018 64.7641 17.4423 66.3298 17.4423C67.855 17.4423 69.0954 16.2018 69.0954 14.636C69.0954 13.0702 67.855 11.8298 66.3298 11.8298ZM99.8623 11.3214H95.5716C95.3886 11.3214 95.2259 11.4841 95.2259 11.6671V19.9841H88.495V11.6671C88.495 11.4841 88.3323 11.3214 88.1493 11.3214H83.818C83.6349 11.3214 83.4723 11.4841 83.4723 11.6671V34.2593C83.4723 34.4423 83.6553 34.605 83.818 34.605H88.1493C88.3323 34.605 88.495 34.4423 88.495 34.2593V24.6002H95.2259L95.1852 34.2593C95.1852 34.4423 95.3479 34.605 95.5309 34.605H99.8623C100.045 34.605 100.208 34.4423 100.208 34.2593V11.6671C100.208 11.4841 100.045 11.3214 99.8623 11.3214ZM61.4901 21.3262V32.9985C61.4901 33.0799 61.4698 33.2222 61.3681 33.2629C61.3681 33.2629 58.8262 35.0727 54.6372 35.0727C49.5738 35.0727 43.575 33.4866 43.575 23.0344C43.575 12.5822 48.8214 10.4267 53.9458 10.447C58.3789 10.447 60.1683 11.4434 60.453 11.6264C60.5344 11.7281 60.575 11.8095 60.575 11.9111L59.721 15.5308C59.721 15.7138 59.538 15.9375 59.3143 15.8765C58.5822 15.6528 57.4841 15.2054 54.9016 15.2054C51.9123 15.2054 48.6994 16.0595 48.6994 22.7904C48.6994 29.5212 51.7497 30.3143 53.9458 30.3143C55.8167 30.3143 56.4877 30.0906 56.4877 30.0906V25.4136H53.4985C53.2748 25.4136 53.1121 25.2509 53.1121 25.0679V21.3262C53.1121 21.1432 53.2748 20.9805 53.4985 20.9805H61.1038C61.3274 20.9805 61.4901 21.1432 61.4901 21.3262Z"/>'
    '</svg>'
)


CLIENT_CARDS: list[dict[str, Any]] = [
    {
        "id": "claude",
        "title": "Claude Code",
        "desc": "Anthropic Messages API CLI (Base URL without /v1)",
        "desc_en": "Anthropic Messages API CLI (Base URL without /v1)",
        "desc_es": "CLI con Anthropic Messages API (URL base sin /v1)",
        "icon_svg": CLAUDE_ICON_SVG,
        "auto_cmd": lambda addr: (
            f"agy-bridge setup-claude --port {addr.rsplit(':', 1)[1]}"
            if ":" in addr and addr.rsplit(":", 1)[1].isdigit() and addr.rsplit(":", 1)[1] != "24980"
            else "agy-bridge setup-claude"
        ),
        "restore_cmd": lambda addr: "agy-bridge restore-claude",
        "manual_snippet": lambda addr: f'export ANTHROPIC_BASE_URL="http://{addr}"\nexport ANTHROPIC_AUTH_TOKEN="local-bridge"',
        "docs_url": "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview",
    },
    {
        "id": "codex",
        "title": "Codex CLI",
        "desc": "OpenAI Responses API CLI (wire_api = 'responses')",
        "desc_en": "OpenAI Responses API CLI (wire_api = 'responses')",
        "desc_es": "CLI con OpenAI Responses API (wire_api = 'responses')",
        "icon_svg": CODEX_ICON_SVG,
        "auto_cmd": lambda addr: (
            f"agy-bridge setup-codex --port {addr.rsplit(':', 1)[1]}"
            if ":" in addr and addr.rsplit(":", 1)[1].isdigit() and addr.rsplit(":", 1)[1] != "24980"
            else "agy-bridge setup-codex"
        ),
        "restore_cmd": lambda addr: "agy-bridge restore-codex",
        "manual_snippet": lambda addr: (
            f'# ~/.codex/config.toml\n'
            f'model = "gemini-3.8-flash-high"\n'
            f'model_provider = "agy"\n'
            f'model_context_window = 1048576\n'
            f'model_auto_compact_token_limit = 943718\n\n'
            f'[model_providers.agy]\n'
            f'name = "agy"\n'
            f'base_url = "http://{addr}/v1"\n'
            f'wire_api = "responses"\n'
            f'requires_openai_auth = false'
        ),
        "docs_url": "https://github.com/openai/codex",
    },
    {
        "id": "hermes",
        "title": "Hermes Agent",
        "desc": "NousResearch Hermes Agent CLI (Base URL with /v1)",
        "desc_en": "NousResearch Hermes Agent CLI (Base URL with /v1)",
        "desc_es": "CLI de Hermes Agent de NousResearch (URL base con /v1)",
        "auto_cmd": lambda addr: f'export OPENAI_BASE_URL="http://{addr}/v1" OPENAI_API_KEY="local-bridge" && hermes',
        "manual_snippet": lambda addr: f'export OPENAI_BASE_URL="http://{addr}/v1"\nexport OPENAI_API_KEY="local-bridge"',
        "docs_url": "https://hermes-agent.nousresearch.com",
    },
    {
        "id": "freellmapi",
        "title": "FreeLLMAPI",
        "desc": "Custom Provider & Aider integration (Base URL with /v1)",
        "desc_en": "Custom Provider & Aider integration (Base URL with /v1)",
        "desc_es": "Integración para Custom Provider y Aider (URL base con /v1)",
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
    lang: str = "en",
) -> str:
    """Renders the self-contained dark-mode HTML dashboard for the local AI gateway."""
    is_es = bool(lang and str(lang).strip().lower().startswith("es"))
    html_lang = "es" if is_es else "en"
    active_en = " active" if not is_es else ""
    active_es = " active" if is_es else ""

    safe_host = html.escape(str(host))
    safe_port = html.escape(str(port))
    address = f"{safe_host}:{safe_port}"

    snippet_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else safe_host
    snippet_address = f"{snippet_host}:{safe_port}"

    status_name = auth_status.get("status", "Missing")
    email = auth_status.get("email")
    message = auth_status.get("message", "")

    subtitle_text = (
        "Gateway multiprotocolo sin dependencias para Google Cloud Code Assist"
        if is_es
        else "Zero-dependency multi-protocol gateway to Google Cloud Code Assist"
    )

    if status_name == "Valid":
        auth_badge_class = "badge-success"
        auth_word = "Válido" if is_es else "Valid"
        auth_label = f"{auth_word} ({email})" if email else auth_word
    elif status_name == "Expired":
        auth_badge_class = "badge-warning"
        auth_label = "Expirado — Abrí Antigravity para renovar" if is_es else f"Expired — {message}"
    else:
        auth_badge_class = "badge-danger"
        auth_label = "Faltante — Abrí Antigravity para renovar" if is_es else f"Missing — {message}"

    models_label = f"{models_count} Modelos Descubiertos" if is_es else f"{models_count} Models Discovered"
    setup_auto_title = "Configuración automática" if is_es else "Automatic configuration"
    setup_manual_title = "Conexión manual" if is_es else "Manual connection"
    setup_restore_title = "Restaurar configuración" if is_es else "Restore configuration"
    copy_btn_title = "Copiar" if is_es else "Copy"
    docs_link_title = "Documentación ↗" if is_es else "Documentation ↗"
    footer_text = (
        "AGY Model Bridge &bull; Potenciado por Google Cloud Code Assist &bull; Gateway local"
        if is_es
        else "AGY Model Bridge &bull; Powered by Google Cloud Code Assist &bull; Local Gateway"
    )

    cards_html_parts: list[str] = []
    for card in CLIENT_CARDS:
        auto_text = card["auto_cmd"](snippet_address)
        manual_text = card["manual_snippet"](snippet_address)
        card_id = card["id"]
        icon_html = card.get("icon_svg", "")
        desc_text = card.get("desc_es" if is_es else "desc_en", card.get("desc", ""))

        restore_block_html = ""
        if "restore_cmd" in card:
            restore_text = card["restore_cmd"](snippet_address)
            restore_block_html = f"""
        <div class="setup-block">
          <div class="setup-header">
            <span class="setup-title" data-i18n="setup_restore">{setup_restore_title}</span>
            <button class="copy-btn" data-i18n="btn_copy" onclick="copySnippet(this, '{card_id}-restore')">{copy_btn_title}</button>
          </div>
          <pre id="{card_id}-restore"><code>{html.escape(restore_text)}</code></pre>
        </div>"""

        cards_html_parts.append(f"""      <section class="card">
        <div class="card-header">
          <h2 class="card-title">{icon_html}{html.escape(card["title"])}</h2>
        </div>
        <p class="card-desc" data-i18n="desc_{card_id}">{html.escape(desc_text)}</p>

        <div class="setup-block">
          <div class="setup-header">
            <span class="setup-title" data-i18n="setup_auto">{setup_auto_title}</span>
            <button class="copy-btn" data-i18n="btn_copy" onclick="copySnippet(this, '{card_id}-auto')">{copy_btn_title}</button>
          </div>
          <pre id="{card_id}-auto"><code>{html.escape(auto_text)}</code></pre>
        </div>

        <div class="setup-block">
          <div class="setup-header">
            <span class="setup-title" data-i18n="setup_manual">{setup_manual_title}</span>
            <button class="copy-btn" data-i18n="btn_copy" onclick="copySnippet(this, '{card_id}-manual')">{copy_btn_title}</button>
          </div>
          <pre id="{card_id}-manual"><code>{html.escape(manual_text)}</code></pre>
        </div>{restore_block_html}

        <div class="card-footer">
          <a href="{html.escape(card["docs_url"])}" target="_blank" rel="noopener noreferrer" class="docs-link" data-i18n="docs_link">{docs_link_title}</a>
        </div>
      </section>""")
    cards_html = "\n".join(cards_html_parts)

    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
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
    .header-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 1.5rem;
    }}
    .header-actions {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      flex-shrink: 0;
      margin-top: 0.15rem;
    }}
    .lang-switcher {{
      display: inline-flex;
      align-items: center;
      gap: 0.25rem;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 0.25rem 0.5rem;
    }}
    .lang-btn {{
      background: transparent;
      border: none;
      color: var(--text-secondary);
      cursor: pointer;
      padding: 0.2rem 0.45rem;
      border-radius: 6px;
      font-family: var(--font-sans);
      font-size: 0.75rem;
      font-weight: 600;
      transition: color 0.15s ease, background 0.15s ease;
    }}
    .lang-btn:hover {{
      color: var(--text-primary);
    }}
    .lang-btn.active {{
      color: var(--accent);
      background: rgba(56, 189, 248, 0.12);
    }}
    .lang-divider {{
      color: var(--card-border);
      font-size: 0.75rem;
    }}
    .github-link {{
      display: inline-flex;
      align-items: center;
      padding: 0.45rem 0.8rem;
      border: 1px solid var(--card-border);
      border-radius: 10px;
      background: var(--card-bg);
      color: var(--text-secondary);
      text-decoration: none;
      transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
      flex-shrink: 0;
      margin-top: 0.15rem;
    }}
    .github-link:hover {{
      color: var(--text-primary);
      border-color: #444444;
      background: #1a1a1a;
    }}
    .github-link svg {{
      height: 20px;
      width: auto;
      display: block;
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
      .header-top {{
        flex-direction: column;
        align-items: flex-start;
        gap: 0.75rem;
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
      display: flex;
      align-items: center;
      gap: 0.6rem;
    }}
    .card-icon {{
      display: inline-block;
      flex-shrink: 0;
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
      <div class="header-top">
        <div>
          <h1>AGY Model Bridge</h1>
          <p class="subtitle" data-i18n="subtitle">{subtitle_text}</p>
        </div>
        <div class="header-actions">
          <div class="lang-switcher" role="group" aria-label="Language switcher">
            <button type="button" id="btn-lang-en" class="lang-btn{active_en}" onclick="setLanguage('en')">EN</button>
            <span class="lang-divider">|</span>
            <button type="button" id="btn-lang-es" class="lang-btn{active_es}" onclick="setLanguage('es')">ES</button>
          </div>
          <a href="https://github.com/albertopo94/agy-model-bridge" target="_blank" rel="noopener noreferrer" class="github-link" title="GitHub Repository">
            {GITHUB_ICON_SVG}
          </a>
        </div>
      </div>
      <div class="badges">
        <span class="badge">🌐 {address}</span>
        <span class="badge {auth_badge_class}" data-i18n="auth" data-status="{html.escape(status_name)}" data-email="{html.escape(email or '')}">🛡️ {html.escape(auth_label)}</span>
        <span class="badge badge-models" data-i18n="models" data-count="{models_count}">⚡ {models_label}</span>
      </div>
    </header>

    <main class="cards-grid">
{cards_html}
    </main>

    <footer>
      <p data-i18n="footer">{footer_text}</p>
    </footer>
  </div>

  <script>
    var currentLang = "{html_lang}";

    var I18N = {{
      en: {{
        subtitle: "Zero-dependency multi-protocol gateway to Google Cloud Code Assist",
        models: "{{count}} Models Discovered",
        auth_valid: "Valid",
        auth_expired: "Expired — Open Antigravity to refresh",
        auth_missing: "Missing — Open Antigravity to refresh",
        setup_auto: "Automatic configuration",
        setup_manual: "Manual connection",
        setup_restore: "Restore configuration",
        docs_link: "Documentation ↗",
        btn_copy: "Copy",
        btn_copied: "Copied!",
        desc_claude: "Anthropic Messages API CLI (Base URL without /v1)",
        desc_codex: "OpenAI Responses API CLI (wire_api = 'responses')",
        desc_hermes: "NousResearch Hermes Agent CLI (Base URL with /v1)",
        desc_freellmapi: "Custom Provider & Aider integration (Base URL with /v1)",
        footer: "AGY Model Bridge &bull; Powered by Google Cloud Code Assist &bull; Local Gateway"
      }},
      es: {{
        subtitle: "Gateway multiprotocolo sin dependencias para Google Cloud Code Assist",
        models: "{{count}} Modelos Descubiertos",
        auth_valid: "V\u00e1lido",
        auth_expired: "Expirado \u2014 Abr\u00ed Antigravity para renovar",
        auth_missing: "Faltante \u2014 Abr\u00ed Antigravity para renovar",
        setup_auto: "Configuraci\u00f3n autom\u00e1tica",
        setup_manual: "Conexi\u00f3n manual",
        setup_restore: "Restaurar configuraci\u00f3n",
        docs_link: "Documentaci\u00f3n \u2197",
        btn_copy: "Copiar",
        btn_copied: "\u00a1Copiado!",
        desc_claude: "CLI con Anthropic Messages API (URL base sin /v1)",
        desc_codex: "CLI con OpenAI Responses API (wire_api = 'responses')",
        desc_hermes: "CLI de Hermes Agent de NousResearch (URL base con /v1)",
        desc_freellmapi: "Integraci\u00f3n para Custom Provider y Aider (URL base con /v1)",
        footer: "AGY Model Bridge &bull; Potenciado por Google Cloud Code Assist &bull; Gateway local"
      }}
    }};

    function setLanguage(lang) {{
      var effectiveLang = (lang === "es") ? "es" : "en";
      currentLang = effectiveLang;
      try {{
        localStorage.setItem("agy_lang", effectiveLang);
      }} catch(e) {{}}
      document.documentElement.lang = effectiveLang;

      var btnEn = document.getElementById("btn-lang-en");
      var btnEs = document.getElementById("btn-lang-es");
      if (btnEn && btnEs) {{
        if (effectiveLang === "es") {{
          btnEs.classList.add("active");
          btnEn.classList.remove("active");
        }} else {{
          btnEn.classList.add("active");
          btnEs.classList.remove("active");
        }}
      }}

      var dict = I18N[effectiveLang] || I18N.en;

      var elements = document.querySelectorAll("[data-i18n]");
      for (var i = 0; i < elements.length; i++) {{
        var el = elements[i];
        var key = el.getAttribute("data-i18n");
        if (key === "models") {{
          var count = el.getAttribute("data-count") || "0";
          var tpl = dict.models || "{{count}} Models Discovered";
          el.innerHTML = "⚡ " + tpl.replace("{{count}}", count);
        }} else if (key === "auth") {{
          var st = el.getAttribute("data-status");
          var email = el.getAttribute("data-email");
          var label = "";
          if (st === "Valid") {{
            var validText = dict.auth_valid || "Valid";
            label = email ? (validText + " (" + email + ")") : validText;
          }} else if (st === "Expired") {{
            label = dict.auth_expired || "Expired — Open Antigravity to refresh";
          }} else {{
            label = dict.auth_missing || "Missing — Open Antigravity to refresh";
          }}
          el.innerHTML = "🛡️ " + label;
        }} else if (key === "btn_copy") {{
          if (!el.classList.contains("copied")) {{
            el.innerText = dict.btn_copy || "Copy";
          }}
        }} else if (dict[key]) {{
          el.innerHTML = dict[key];
        }}
      }}
    }}

    (function initLang() {{
      var saved = null;
      try {{
        saved = localStorage.getItem("agy_lang");
      }} catch(e) {{}}
      if (saved === "es" || saved === "en") {{
        setLanguage(saved);
      }}
    }})();

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
      }} catch (e) {{}}
    }}

    function setCopied(btn) {{
      if (btn.classList.contains("copied")) return;
      var dict = I18N[currentLang] || I18N.en;
      btn.innerText = dict.btn_copied || "Copied!";
      btn.classList.add("copied");
      setTimeout(function() {{
        btn.innerText = dict.btn_copy || "Copy";
        btn.classList.remove("copied");
      }}, 2000);
    }}
  </script>
</body>
</html>"""
