#!/usr/bin/env python3
"""Standalone multi-protocol smoke test script for Antigravity Model Bridge."""

import argparse
import html
import json
import sys
import urllib.error
import urllib.request



def get_default_api_key() -> str:
    try:
        from bridge.security import get_or_create_api_key
        return get_or_create_api_key()
    except Exception:
        return "local-bridge"


def test_healthz(base_url: str) -> None:
    print("[1/9] Verifying GET /healthz ... ", end="", flush=True)
    url = f"{base_url}/healthz"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            if resp.status != 200:
                raise AssertionError(f"Expected HTTP 200, got {resp.status}")
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") != "ok" or data.get("service") != "agy-model-bridge":
                raise AssertionError(f"Expected status 'ok' and service 'agy-model-bridge', got {data}")
    except Exception as e:
        print("FAILED")
        print(f"Error in health check: {e}", file=sys.stderr)
        sys.exit(1)
    print("OK")


def test_models(base_url: str, api_key: str = "local-bridge") -> str:
    print("[2/9] Verifying GET /v1/models ... ", end="", flush=True)
    url = f"{base_url}/v1/models"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    chosen_model = ""
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            if resp.status != 200:
                raise AssertionError(f"Expected HTTP 200, got {resp.status}")
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("data", [])
            if not isinstance(models, list) or len(models) == 0:
                raise AssertionError(f"Expected non-empty model list, got {models}")
            gemini_models = [m.get("id", "") for m in models if m.get("id", "").startswith("gemini-") and "-image" not in m.get("id", "")]
            flash_models = [m.get("id", "") for m in models if "flash" in m.get("id", "") and not m.get("id", "").startswith("tab_") and "-image" not in m.get("id", "")]
            chosen_model = gemini_models[0] if gemini_models else (flash_models[0] if flash_models else models[0].get("id", ""))
            if not chosen_model:
                raise AssertionError(f"Invalid model entry in catalog: {models[0]}")
    except Exception as e:
        print("FAILED")
        print(f"Error in models retrieval: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK (Found {len(models)} models, using '{chosen_model}')")
    return chosen_model


def test_dashboard(base_url: str) -> None:
    print("[3/9] Verifying GET / (Gateway Dashboard) ... ", end="", flush=True)
    url = f"{base_url}/"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            if resp.status != 200:
                raise AssertionError(f"Expected HTTP 200, got {resp.status}")
            content_type = resp.headers.get_content_type()
            if "text/html" not in content_type:
                raise AssertionError(f"Expected text/html content type, got {content_type}")
            html_body = resp.read().decode("utf-8")
            if "AGY Model Bridge" not in html_body:
                raise AssertionError("Missing 'AGY Model Bridge' title in dashboard HTML")
            for card in ("Claude Code", "Codex CLI", "Hermes Agent", "FreeLLMAPI"):
                if card not in html_body:
                    raise AssertionError(f"Missing client card '{card}' in dashboard HTML")
            for section in ("Configuración automática", "Conexión manual"):
                if section not in html_body:
                    raise AssertionError(f"Missing setup section '{section}' in dashboard HTML")
            if "Documentación" not in html_body:
                raise AssertionError("Missing 'Documentación' external links in dashboard HTML")
            for expected_url in (
                "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview",
                "https://github.com/openai/codex",
            ):
                if expected_url not in html_body:
                    raise AssertionError(f"Missing doc URL '{expected_url}' in dashboard HTML")
            unescaped_body = html.unescape(html_body)
            for expected_snippet in (
                "# ~/.codex/config.toml",
                "[model_providers.agy]",
                'wire_api = "responses"',
                "export ANTHROPIC_BASE_URL=",
                "BASE_URL=",
            ):
                if expected_snippet not in unescaped_body:
                    raise AssertionError(f"Missing snippet pattern '{expected_snippet}' in dashboard HTML")


    except Exception as e:
        print("FAILED")
        print(f"Error in dashboard retrieval: {e}", file=sys.stderr)
        sys.exit(1)
    print("OK")


def test_chat_non_streaming(base_url: str, model: str, api_key: str = "local-bridge") -> None:
    print(f"[4/9] Verifying POST /v1/chat/completions (stream=False, model='{model}') ... ", end="", flush=True)
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Respond with the word 'HELLO' only."}
        ],
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            if resp.status != 200:
                raise AssertionError(f"Expected HTTP 200, got {resp.status}")
            res = json.loads(resp.read().decode("utf-8"))
            choices = res.get("choices", [])
            if not choices or not isinstance(choices, list):
                raise AssertionError(f"Expected non-empty choices list, got: {res}")
            content = choices[0].get("message", {}).get("content", "")
            if not content or not isinstance(content, str) or not content.strip():
                raise AssertionError(f"Expected non-empty response content, got: {content}")
    except Exception as e:
        print("FAILED")
        print(f"Error in non-streaming completion: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK (Received: {content.strip()!r})")


def test_chat_streaming(base_url: str, model: str, api_key: str = "local-bridge") -> None:
    print(f"[5/9] Verifying POST /v1/chat/completions (stream=True, model='{model}') ... ", end="", flush=True)
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Respond with the word 'WORLD' only."}
        ],
        "stream": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    received_chunks: list[str] = []
    saw_done = False
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            if resp.status != 200:
                raise AssertionError(f"Expected HTTP 200, got {resp.status}")
            content_type = resp.headers.get_content_type()
            if content_type != "text/event-stream":
                raise AssertionError(f"Expected text/event-stream, got {content_type}")

            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                if line == "data: [DONE]":
                    saw_done = True
                    break
                if line.startswith("data: "):
                    chunk = json.loads(line[6:])
                    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        received_chunks.append(delta)

        if not saw_done:
            raise AssertionError("Stream completed without data: [DONE] terminator")
        full_text = "".join(received_chunks)
        if not full_text.strip():
            raise AssertionError("Expected non-empty streaming text, got empty")
    except Exception as e:
        print("FAILED")
        print(f"Error in streaming completion: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK (Streamed: {full_text.strip()!r})")


def test_anthropic_non_streaming(base_url: str, model: str, api_key: str = "local-bridge") -> None:
    print(f"[6/9] Verifying POST /v1/messages (stream=False, model='{model}', output_config.effort='high') ... ", end="", flush=True)
    url = f"{base_url}/v1/messages"
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Respond with the word 'ANTHROPIC' only."}
        ],
        "max_tokens": 1000,
        "output_config": {"effort": "high"},
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            if resp.status != 200:
                raise AssertionError(f"Expected HTTP 200, got {resp.status}")
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("type") != "message":
                raise AssertionError(f"Expected type 'message', got {res.get('type')}")
            if res.get("role") != "assistant":
                raise AssertionError(f"Expected role 'assistant', got {res.get('role')}")
            content = res.get("content", [])
            if not content or not isinstance(content, list):
                raise AssertionError(f"Expected non-empty content list, got: {res}")
            text_parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            text = "".join(text_parts)
            if not text or not text.strip():
                raise AssertionError(f"Expected non-empty text in content, got: {content}")
    except Exception as e:
        print("FAILED")
        print(f"Error in Anthropic non-streaming completion: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK (Received: {text.strip()!r})")


def test_anthropic_streaming(base_url: str, model: str, api_key: str = "local-bridge") -> None:
    print(f"[7/9] Verifying POST /v1/messages (stream=True, model='{model}') ... ", end="", flush=True)
    url = f"{base_url}/v1/messages"
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Respond with the word 'CLAUDE' only."}
        ],
        "max_tokens": 1000,
        "stream": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    received_chunks: list[str] = []
    saw_message_stop = False
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            if resp.status != 200:
                raise AssertionError(f"Expected HTTP 200, got {resp.status}")
            content_type = resp.headers.get_content_type()
            if "text/event-stream" not in content_type:
                raise AssertionError(f"Expected text/event-stream, got {content_type}")

            current_event = None
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                    if current_event == "message_stop":
                        saw_message_stop = True
                elif line.startswith("data: "):
                    data_obj = json.loads(line[6:])
                    if current_event == "content_block_delta":
                        delta_dict = data_obj.get("delta", {})
                        delta_text = delta_dict.get("text", "") or delta_dict.get("thinking", "")
                        if delta_text:
                            received_chunks.append(delta_text)

        if not saw_message_stop:
            raise AssertionError("Stream completed without message_stop event")
        full_text = "".join(received_chunks)
        if not full_text.strip():
            raise AssertionError("Expected non-empty streaming text, got empty")
    except Exception as e:
        print("FAILED")
        print(f"Error in Anthropic streaming completion: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK (Streamed: {full_text.strip()!r})")


def test_responses_non_streaming(base_url: str, model: str, api_key: str = "local-bridge") -> None:
    print(f"[8/9] Verifying POST /v1/responses (stream=False, model='{model}') ... ", end="", flush=True)
    url = f"{base_url}/v1/responses"
    payload = {
        "model": model,
        "input": [
            "Respond with the word 'RESPONSES' only."
        ],
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            if resp.status != 200:
                raise AssertionError(f"Expected HTTP 200, got {resp.status}")
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("object") != "response":
                raise AssertionError(f"Expected object 'response', got {res.get('object')}")
            if res.get("status") != "completed":
                raise AssertionError(f"Expected status 'completed', got {res.get('status')}")
            output = res.get("output", [])
            if not output or not isinstance(output, list):
                raise AssertionError(f"Expected non-empty output list, got: {res}")
            item = output[0]
            content = item.get("content", [])
            if not content or not isinstance(content, list):
                raise AssertionError(f"Expected non-empty content in output item, got: {item}")
            text = content[0].get("text", "")
            if not text or not text.strip():
                raise AssertionError(f"Expected non-empty text in output content, got: {text}")
    except Exception as e:
        print("FAILED")
        print(f"Error in Responses non-streaming completion: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK (Received: {text.strip()!r})")


def test_responses_streaming(base_url: str, model: str, api_key: str = "local-bridge") -> None:
    print(f"[9/9] Verifying POST /v1/responses (stream=True, model='{model}') ... ", end="", flush=True)
    url = f"{base_url}/v1/responses"
    payload = {
        "model": model,
        "input": [
            "Respond with the word 'CODEX' only."
        ],
        "stream": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    received_chunks: list[str] = []
    saw_completed = False
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            if resp.status != 200:
                raise AssertionError(f"Expected HTTP 200, got {resp.status}")
            content_type = resp.headers.get_content_type()
            if "text/event-stream" not in content_type:
                raise AssertionError(f"Expected text/event-stream, got {content_type}")

            current_event = None
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                    if current_event == "response.completed":
                        saw_completed = True
                elif line.startswith("data: "):
                    data_obj = json.loads(line[6:])
                    if current_event == "response.output_text.delta":
                        delta_text = data_obj.get("delta", "")
                        if delta_text:
                            received_chunks.append(delta_text)

        if not saw_completed:
            raise AssertionError("Stream completed without response.completed event")
        full_text = "".join(received_chunks)
        if not full_text.strip():
            raise AssertionError("Expected non-empty streaming text, got empty")
    except Exception as e:
        print("FAILED")
        print(f"Error in Responses streaming completion: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK (Streamed: {full_text.strip()!r})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-protocol smoke test for Antigravity Model Bridge")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bridge host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=24980, help="Bridge port (default: 24980)")
    parser.add_argument("--model", type=str, default=None, help="Model override")
    parser.add_argument("--api-key", type=str, default=None, help="Bridge API key (default: read from ~/.agy-bridge/api_key)")
    args = parser.parse_args()

    api_key = args.api_key or get_default_api_key()
    base_url = f"http://{args.host}:{args.port}"
    print(f"Starting 9-step multi-protocol smoke test against {base_url} ...\n")

    test_healthz(base_url)
    model = args.model if args.model else test_models(base_url, api_key)
    test_dashboard(base_url)
    test_chat_non_streaming(base_url, model, api_key)
    test_chat_streaming(base_url, model, api_key)
    test_anthropic_non_streaming(base_url, model, api_key)
    test_anthropic_streaming(base_url, model, api_key)
    test_responses_non_streaming(base_url, model, api_key)
    test_responses_streaming(base_url, model, api_key)

    print("\nAll 9 multi-protocol smoke tests passed successfully! [100% OK]")
    sys.exit(0)


if __name__ == "__main__":
    main()
