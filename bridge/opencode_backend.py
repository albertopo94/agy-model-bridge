"""OpenCode CLI backend: free-tier model discovery and execution adapter.

Zero external dependencies: pure standard library.

Exposes OpenCode free-tier models (`opencode/*-free`) as a third upstream next
to Antigravity and Cursor. Display names carry a trailing `[OpenCode]` source
tag for parity with Cursor's `[Cursor - Free]` / `[Cursor - Pro]` tags.

Execution prefers a warm `opencode acp` process and falls back to
`opencode run -m <model> --format json --pure` subprocesses, mirroring the
Cursor ACP-then-CLI strategy.
"""

from __future__ import annotations

from bridge.errors import AuthenticationError, BridgeError, ForbiddenError, UpstreamTimeoutError
from bridge.opencode_acp import (
    OpencodeAcpClient,
    extract_opencode_error_message,
    find_opencode_binary,
    is_opencode_auth_error,
    is_opencode_region_error,
)
from collections.abc import Iterable, Iterator
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any

OPENCODE_PROVIDER_PREFIX = "opencode/"
DEFAULT_OPENCODE_MODEL = "opencode/pulse-alpha-free"

# Static fallback used when `opencode models` is unavailable or slow, so the
# catalog never advertises paid or other-provider models by accident.
OPENCODE_FREE_MODELS: set[str] = {
    "opencode/beam-free",
    "opencode/deepseek-v4.1-flash-free",
    "opencode/flint-40b-free",
    "opencode/glm-5.3-flash-free",
    "opencode/mimo-v2.6-flash-free",
    "opencode/nemotron-3.5-lightning-free",
    "opencode/nemotron-3.5-super-vl-free",
    "opencode/pulse-alpha-free",
}

OPENCODE_KNOWN_DISPLAY_NAMES: dict[str, str] = {
    "big-pickle": "Big Pickle",
}

_ACRONYMS = {"vl", "glm", "ai", "api", "3p"}

_MODEL_LINE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*/[a-zA-Z0-9._-]+$")


def is_opencode_model(model: str) -> bool:
    """Checks whether the requested model belongs to the OpenCode upstream."""
    if not model or not isinstance(model, str):
        return False
    return model.strip().lower().startswith(OPENCODE_PROVIDER_PREFIX)


def is_opencode_free_model(model: str) -> bool:
    """Checks whether an OpenCode model id is a free-tier model (S2)."""
    if not is_opencode_model(model):
        return False
    return model.strip().lower().endswith("-free")


def resolve_opencode_model(model: str) -> str:
    """Normalizes a model name to the `provider/model` id OpenCode expects."""
    if not model or not isinstance(model, str):
        return DEFAULT_OPENCODE_MODEL
    m = model.strip()
    if not m:
        return DEFAULT_OPENCODE_MODEL
    if "/" in m:
        return m
    return f"{OPENCODE_PROVIDER_PREFIX}{m}"


def _capitalize_segment(segment: str) -> str:
    low = segment.lower()
    if low in _ACRONYMS:
        return segment.upper()
    if low.startswith("deepseek"):
        return "DeepSeek" + segment[len("deepseek"):]
    if re.fullmatch(r"[0-9]+(\.[0-9]+)?", segment):
        return segment
    if segment[0].isupper():
        return segment
    return segment.capitalize()


def format_opencode_model_display_name(model_id: str) -> str:
    """Formats a user-facing display name with the trailing [OpenCode] source tag."""
    clean = resolve_opencode_model(model_id)
    if clean.startswith(OPENCODE_PROVIDER_PREFIX):
        clean = clean[len(OPENCODE_PROVIDER_PREFIX):]
    clean = clean.strip()
    if not clean:
        return "OpenCode [OpenCode]"

    base = OPENCODE_KNOWN_DISPLAY_NAMES.get(clean)
    if not base:
        base = " ".join(_capitalize_segment(p) for p in re.split(r"[-_]+", clean) if p)
    return f"{base} [OpenCode]"


def parse_run_events(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """Parses `opencode run --format json` lines into (kind, payload) events.

    kind is "text" for assistant text deltas or "error" for an upstream error
    message. Malformed or unrelated lines are ignored.
    """
    buffer = ""
    for raw in lines:
        if not isinstance(raw, str):
            continue
        line = raw.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(msg, dict):
            continue

        mtype = msg.get("type")
        if mtype == "error":
            payload = msg.get("error") or msg.get("data") or msg
            yield ("error", extract_opencode_error_message(payload))
            continue
        if mtype != "text":
            continue

        part = msg.get("part")
        text = part.get("text") if isinstance(part, dict) else None
        if not isinstance(text, str) or not text:
            continue
        if text == buffer:
            continue
        if text.startswith(buffer):
            diff = text[len(buffer):]
            buffer = text
            if diff:
                yield ("text", diff)
        else:
            buffer += text
            yield ("text", text)


def _map_opencode_error(model: str, message: str) -> BridgeError:
    """Maps a raw upstream error message to the bridge exception hierarchy."""
    if is_opencode_region_error(message):
        return ForbiddenError(
            f"OpenCode model '{model}' is not available in your region (upstream: {message})"
        )
    if is_opencode_auth_error(message):
        return AuthenticationError(
            f"OpenCode model '{model}' requires provider authentication (upstream: {message})"
        )
    return BridgeError(f"OpenCode upstream error for model '{model}': {message or 'unknown error'}")


class OpencodeBackend:
    """Backend adapter that delegates inference to the local OpenCode CLI."""

    def __init__(
        self,
        binary_path: str | None = None,
        acp_client: Any | None = None,
        use_acp: bool | None = None,
    ) -> None:
        self.binary_path = binary_path or find_opencode_binary()
        if use_acp is None:
            self.use_acp = os.environ.get("OPENCODE_DISABLE_ACP", "").strip() not in ("1", "true")
        else:
            self.use_acp = use_acp
        self._acp_client = acp_client
        self._acp_client_lock = threading.Lock()
        self._cached_models: list[dict[str, Any]] | None = None
        self._cached_models_time: float = 0.0
        self._models_lock = threading.Lock()

    def _get_acp_client(self) -> Any:
        if self._acp_client is not None:
            return self._acp_client
        with self._acp_client_lock:
            if self._acp_client is None:
                client = OpencodeAcpClient(binary_path=self.binary_path)
                client.start()
                self._acp_client = client
            return self._acp_client

    def warmup(self, async_mode: bool = True) -> None:
        """Pre-warms the background OpenCode ACP process without blocking callers."""
        if not self.use_acp:
            return

        def _do_warmup() -> None:
            try:
                acp = self._get_acp_client()
                if not acp.is_alive():
                    acp.start()
            except Exception as exc:
                import sys
                sys.stderr.write(f"Warning: OpenCode ACP warmup failed: {exc}\n")
                sys.stderr.flush()

        if async_mode:
            threading.Thread(target=_do_warmup, daemon=True, name="opencode-acp-warmup").start()
        else:
            _do_warmup()

    def close(self) -> None:
        """Closes any active ACP background client."""
        with self._acp_client_lock:
            if self._acp_client is not None and hasattr(self._acp_client, "close"):
                self._acp_client.close()
                self._acp_client = None

    def is_available(self) -> bool:
        """Returns True when the OpenCode binary can be located."""
        return shutil.which(self.binary_path) is not None or Path(self.binary_path).is_file()

    def status(self) -> dict[str, Any]:
        """Reports availability for the dashboard OpenCode tab (S6).

        OpenCode exposes no provider-side quota API, so `quota_supported` is
        always False and the dashboard must not render fake limit bars.
        """
        available = self.is_available()
        version: str | None = None
        if available:
            with contextlib.suppress(Exception):
                raw = subprocess.check_output(  # noqa: S603
                    [self.binary_path, "--version"],
                    text=True,
                    timeout=2.0,
                    stderr=subprocess.DEVNULL,
                )
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                version = raw.strip().splitlines()[-1].strip() or None

        free_count = 0
        if available:
            with contextlib.suppress(Exception):
                free_count = len(self.list_models())

        return {
            "available": available,
            "binary_path": self.binary_path if available else None,
            "version": version,
            "free_model_count": free_count,
            "quota_supported": False,
        }

    def list_models(self, force: bool = False) -> list[dict[str, Any]]:
        """Discovers free-tier OpenCode models, cached, with a static fallback."""
        now = time.time()
        with self._models_lock:
            if not force and self._cached_models and (now - self._cached_models_time) < 300.0:
                return self._cached_models

        discovered: list[str] = []
        with contextlib.suppress(Exception):
            res = subprocess.run(
                [self.binary_path, "models"],
                capture_output=True,
                text=True,
                check=False,
                timeout=2.0,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    candidate = line.strip()
                    if _MODEL_LINE_RE.match(candidate) and is_opencode_free_model(candidate):
                        discovered.append(candidate)

        if not discovered:
            discovered = sorted(OPENCODE_FREE_MODELS)

        result = [
            {
                "id": m,
                "slug": m,
                "display_name": format_opencode_model_display_name(m),
                "owned_by": "opencode",
            }
            for m in dict.fromkeys(discovered)
        ]
        with self._models_lock:
            self._cached_models = result
            self._cached_models_time = now
        return result

    def stream_chat(
        self,
        prompt: str,
        model: str = DEFAULT_OPENCODE_MODEL,
        timeout: float = 300.0,
    ) -> Iterator[str]:
        """Streams text deltas, preferring the warm ACP process with a CLI fallback."""
        resolved = resolve_opencode_model(model)

        if self.use_acp:
            try:
                acp = self._get_acp_client()
                yield from acp.stream_prompt(prompt, model=resolved, timeout=timeout)
                return
            except (ForbiddenError, AuthenticationError):
                # Availability verdicts are upstream facts; the CLI would only
                # repeat them after paying another cold start.
                raise
            except Exception as acp_err:
                import sys
                sys.stderr.write(
                    f"Warning: OpenCode ACP streaming failed, falling back to opencode run: {acp_err}\n"
                )
                sys.stderr.flush()

        yield from self._stream_chat_cli(prompt=prompt, model=resolved, timeout=timeout)

    def generate_chat(
        self,
        prompt: str,
        model: str = DEFAULT_OPENCODE_MODEL,
        timeout: float = 300.0,
    ) -> str:
        """Collects streaming chunks into a single complete response string."""
        return "".join(self.stream_chat(prompt=prompt, model=model, timeout=timeout))

    def _stream_chat_cli(
        self,
        prompt: str,
        model: str,
        timeout: float,
    ) -> Iterator[str]:
        """Runs `opencode run -m <model> --format json --pure` and yields text deltas."""
        cmd = [
            self.binary_path,
            "run",
            "-m",
            model,
            "--format",
            "json",
            "--pure",
            "--auto",
            prompt,
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise BridgeError(
                f"OpenCode CLI (opencode) not found at '{self.binary_path}'. "
                "Install via: curl -fsSL https://opencode.ai/install | bash"
            ) from exc
        except OSError as exc:
            raise BridgeError(f"Failed to execute OpenCode CLI ({self.binary_path}): {exc}") from exc

        if proc.stdout is None:
            if proc.poll() is None:
                proc.kill()
            raise BridgeError(f"OpenCode CLI produced no stdout for model '{model}'")
        start = time.time()
        error_message: str | None = None
        emitted = False
        try:
            for kind, payload in parse_run_events(proc.stdout):
                if (time.time() - start) > timeout:
                    raise UpstreamTimeoutError(f"OpenCode CLI request timed out after {timeout}s")
                if kind == "error":
                    error_message = payload
                    continue
                emitted = True
                yield payload
        finally:
            with contextlib.suppress(Exception):
                proc.stdout.close()
            if proc.poll() is None:
                proc.kill()

        if error_message is not None and not emitted:
            raise _map_opencode_error(model, error_message)
        if proc.returncode not in (0, None) and not emitted and error_message is None:
            stderr_text = ""
            if proc.stderr is not None:
                stderr_text = proc.stderr.read().strip()
            raise BridgeError(
                f"OpenCode CLI failed for model '{model}' (exit {proc.returncode}): {stderr_text[:300]}"
            )


def is_antigravity_model(model: str) -> bool:
    """Returns True when a model id belongs to the Antigravity upstream
    (i.e. it is not a Cursor or OpenCode model)."""
    if not model or not isinstance(model, str):
        return False
    m = model.strip().lower()
    if m.startswith(("cursor/", "cursor-", "opencode/")):
        return False
    return bool(m)
