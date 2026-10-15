"""Cursor CLI (agent) backend execution and message adapter.

Zero external dependencies: pure standard library.
Spawns `agent -p --output-format stream-json --stream-partial-output --yolo`
with prompts piped via stdin, parsing streaming JSON lines into normalized chunks.
"""

from collections.abc import Iterator
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any

from bridge.errors import BridgeError, UpstreamTimeoutError

CURSOR_EXCLUSIVE_MODELS: set[str] = {
    "gpt-5.3-codex",
    "gpt-5.3-codex-low",
    "gpt-5.3-codex-high",
    "gpt-5.3-codex-xhigh",
    "gpt-5.3-codex-fast",
    "gpt-5.3-codex-low-fast",
    "gpt-5.3-codex-high-fast",
    "gpt-5.3-codex-xhigh-fast",
    "gpt-5.2-codex",
    "gpt-5.1-codex-max",
    "composer-2.5",
    "composer-2.5-fast",
    "composer-1.5",
    "composer-1",
    "gpt-5.6-sol-high",
    "gpt-5.6-luna-high",
    "gpt-5.6-terra-high",
    "grok-4.7-low",
    "grok-4.7-medium",
    "grok-4.7-high",
    "grok-4.7-xhigh",
    "cursor-grok-4.5-high",
    "cursor-grok-4.6-high",
}


def find_agent_binary() -> str:
    """Discovers the absolute path to the cursor 'agent' executable."""
    found = shutil.which("agent")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "agent"
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return str(fallback)
    return "agent"


def extract_text_content(content: Any) -> str:
    """Extracts raw string text from message content (string or list of parts)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    text_parts: list[str] = []
    for part in content:
        if isinstance(part, dict):
            if part.get("type") == "text" and "text" in part:
                text_parts.append(str(part.get("text", "")))
        elif isinstance(part, str):
            text_parts.append(part)
    return "".join(text_parts)


def messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    """Converts a list of OpenAI/Anthropic messages into a flattened prompt string for Cursor CLI."""
    non_empty: list[tuple[str, str]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "").strip().lower()
        text = extract_text_content(m.get("content")).strip()
        if text:
            non_empty.append((role, text))

    if not non_empty:
        return ""

    # Common case: single user prompt
    if len(non_empty) == 1 and non_empty[0][0] == "user":
        return non_empty[0][1]

    # Multi-turn conversation: delimit by role
    sections: list[str] = []
    for role, text in non_empty:
        if role == "system":
            sections.append(f"[System]\n{text}")
        elif role == "assistant":
            sections.append(f"[Assistant]\n{text}")
        else:
            sections.append(f"[User]\n{text}")

    return "\n\n".join(sections)


def resolve_cursor_model(model: str) -> str:
    """Resolves a model name string to the model identifier expected by Cursor CLI."""
    if not model or not isinstance(model, str):
        return "auto"

    m = model.strip()
    if m.startswith("cursor/"):
        m = m[7:].strip()
    elif m.startswith("cursor-"):
        m = m[7:].strip()

    if not m:
        return "auto"

    return m


def is_cursor_model(model: str) -> bool:
    """Checks whether the requested model is designated for Cursor."""
    if not model or not isinstance(model, str):
        return False
    m = model.strip().lower()
    if m.startswith("cursor/") or m.startswith("cursor-"):
        return True
    return m in CURSOR_EXCLUSIVE_MODELS


class CursorBackend:
    """Backend adapter that delegates inference to local Cursor CLI (`agent`)."""

    def __init__(self, binary_path: str | None = None) -> None:
        self.binary_path = binary_path or find_agent_binary()
        self._cached_models: list[dict[str, Any]] | None = None
        self._cached_models_time: float = 0.0
        self._models_lock = threading.Lock()

    def stream_chat(
        self,
        prompt: str,
        model: str = "auto",
        timeout: float = 300.0,
        api_key: str | None = None,
        cwd: str | None = None,
    ) -> Iterator[str]:
        """Invokes Cursor CLI in stream-json mode and yields text deltas."""
        resolved_model = resolve_cursor_model(model)
        cmd = [
            self.binary_path,
            "--model",
            resolved_model or "auto",
            "-p",
            "--output-format",
            "stream-json",
            "--stream-partial-output",
            "--yolo",
        ]

        env = os.environ.copy()
        if api_key:
            env["CURSOR_API_KEY"] = api_key

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd or os.getcwd(),
                env=env,
            )
        except FileNotFoundError as exc:
            raise BridgeError(
                f"Cursor CLI (agent) not found at '{self.binary_path}'. "
                "Install via: curl https://cursor.com/install -fsS | bash"
            ) from exc
        except OSError as exc:
            raise BridgeError(f"Failed to execute Cursor CLI ({self.binary_path}): {exc}") from exc

        # Pipe prompt via stdin in background thread
        def write_stdin() -> None:
            try:
                if proc.stdin:
                    proc.stdin.write(prompt.encode("utf-8"))
                    proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        writer_thread = threading.Thread(target=write_stdin, daemon=True)
        writer_thread.start()

        turn_buffer = ""
        emitted_any = False
        start_time = time.time()

        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                if (time.time() - start_time) > timeout:
                    proc.kill()
                    raise UpstreamTimeoutError(f"Cursor CLI request timed out after {timeout}s")

                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                if not isinstance(msg, dict):
                    continue

                msg_type = msg.get("type")
                if msg_type == "assistant":
                    content = msg.get("message", {}).get("content", [])
                    text = extract_text_content(content)
                    if not text:
                        continue

                    if text == turn_buffer:
                        continue

                    if text.startswith(turn_buffer):
                        diff = text[len(turn_buffer):]
                        turn_buffer = text
                        if diff:
                            emitted_any = True
                            yield diff
                    else:
                        turn_buffer += text
                        emitted_any = True
                        yield text

                elif msg_type == "tool_call":
                    turn_buffer = ""

            proc.wait(timeout=10.0)
            if proc.returncode != 0 and not emitted_any:
                assert proc.stderr is not None
                stderr_text = proc.stderr.read().decode("utf-8", errors="replace").strip()
                raise BridgeError(f"Cursor CLI failed with exit code {proc.returncode}: {stderr_text}")

        except subprocess.TimeoutExpired as exc:
            proc.kill()
            raise UpstreamTimeoutError(f"Cursor CLI timed out after {timeout}s") from exc

    def generate_chat(
        self,
        prompt: str,
        model: str = "auto",
        timeout: float = 300.0,
        api_key: str | None = None,
        cwd: str | None = None,
    ) -> str:
        """Collects streaming chunks into a single complete response string."""
        chunks = list(
            self.stream_chat(
                prompt=prompt,
                model=model,
                timeout=timeout,
                api_key=api_key,
                cwd=cwd,
            )
        )
        return "".join(chunks)

    def list_models(self, force: bool = False) -> list[dict[str, Any]]:
        """Queries `agent models` or returns cached/fallback model list."""
        now = time.time()
        with self._models_lock:
            if not force and self._cached_models and (now - self._cached_models_time) < 300.0:
                return self._cached_models

        discovered: list[str] = []
        try:
            res = subprocess.run(
                [self.binary_path, "models"],
                capture_output=True,
                text=True,
                check=False,
                timeout=1.5,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    match = re.match(r"^([a-zA-Z0-9._-]+)\s*-\s*(.+)$", line.strip())
                    if match:
                        model_id = match.group(1).strip()
                        if model_id and model_id != "auto":
                            discovered.append(model_id)
        except Exception:
            pass

        if not discovered:
            discovered = sorted(m for m in CURSOR_EXCLUSIVE_MODELS if m != "auto")

        result = [
            {
                "id": f"cursor/{m}",
                "slug": f"cursor/{m}",
                "display_name": f"{m} (Cursor)",
                "owned_by": "cursor",
            }
            for m in discovered
        ]
        with self._models_lock:
            self._cached_models = result
            self._cached_models_time = now
        return result
