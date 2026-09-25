#!/usr/bin/env python3
"""Standalone smoke test script for Antigravity Model Bridge."""

import argparse
import json
import sys
import urllib.error
import urllib.request


def test_healthz(base_url: str) -> None:
    print("[1/4] Verifying GET /healthz ... ", end="", flush=True)
    url = f"{base_url}/healthz"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            if resp.status != 200:
                raise AssertionError(f"Expected HTTP 200, got {resp.status}")
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") != "ok":
                raise AssertionError(f"Expected status 'ok', got {data}")
    except Exception as e:
        print("FAILED")
        print(f"Error in health check: {e}", file=sys.stderr)
        sys.exit(1)
    print("OK")


def test_models(base_url: str) -> str:
    print("[2/4] Verifying GET /v1/models ... ", end="", flush=True)
    url = f"{base_url}/v1/models"
    req = urllib.request.Request(url, method="GET")
    chosen_model = ""
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            if resp.status != 200:
                raise AssertionError(f"Expected HTTP 200, got {resp.status}")
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("data", [])
            if not isinstance(models, list) or len(models) == 0:
                raise AssertionError(f"Expected non-empty model list, got {models}")
            flash_models = [m.get("id", "") for m in models if "flash" in m.get("id", "")]
            gemini_models = [m.get("id", "") for m in models if m.get("id", "").startswith("gemini-")]
            chosen_model = flash_models[0] if flash_models else (gemini_models[0] if gemini_models else models[0].get("id", ""))
            if not chosen_model:
                raise AssertionError(f"Invalid model entry in catalog: {models[0]}")
    except Exception as e:
        print("FAILED")
        print(f"Error in models retrieval: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK (Found {len(models)} models, using '{chosen_model}')")
    return chosen_model


def test_chat_non_streaming(base_url: str, model: str) -> None:
    print(f"[3/4] Verifying POST /v1/chat/completions (stream=False, model='{model}') ... ", end="", flush=True)
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
        headers={"Content-Type": "application/json"},
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


def test_chat_streaming(base_url: str, model: str) -> None:
    print(f"[4/4] Verifying POST /v1/chat/completions (stream=True, model='{model}') ... ", end="", flush=True)
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
        headers={"Content-Type": "application/json"},
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
            raise AssertionError(f"Expected non-empty streaming text, got empty")
    except Exception as e:
        print("FAILED")
        print(f"Error in streaming completion: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK (Streamed: {full_text.strip()!r})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test for Antigravity Model Bridge")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bridge host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Bridge port (default: 8080)")
    parser.add_argument("--model", type=str, default=None, help="Model override")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    print(f"Starting smoke test against {base_url} ...\n")

    test_healthz(base_url)
    model = args.model if args.model else test_models(base_url)
    test_chat_non_streaming(base_url, model)
    test_chat_streaming(base_url, model)

    print("\nAll smoke tests passed successfully! [100% OK]")
    sys.exit(0)


if __name__ == "__main__":
    main()
