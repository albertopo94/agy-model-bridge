"""Antigravity model quota tracking and provider architecture.

Zero external dependencies: pure standard library.
Reads user quota from the local Antigravity CLI ('agy') via slash print command.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Protocol, runtime_checkable

MIN_USAGE_VERSION: tuple[int, int, int] = (1, 1, 11)


@dataclass(frozen=True, slots=True)
class QuotaBucket:
    """Represents a single quota window bucket within a model pool."""

    id: str
    group: str
    name: str
    label: str
    window: str | None
    used_percent: int
    remaining_fraction: float
    resets_at: float | None
    resets_in: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    """Immutable snapshot of the user's Antigravity quota."""

    status: str  # 'ok' | 'unavailable' | 'error'
    buckets: list[QuotaBucket] = field(default_factory=list)
    description: str | None = None
    updated_at: float = 0.0
    error: str | None = None
    summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "buckets": [b.to_dict() for b in self.buckets],
            "description": self.description,
            "updated_at": self.updated_at,
            "error": self.error,
            "summary": self.summary,
        }


@runtime_checkable
class QuotaProvider(Protocol):
    """Protocol defining the interface for quota providers."""

    def fetch(self, force: bool = False) -> QuotaSnapshot:
        """Retrieves the current quota snapshot."""
        ...


def parse_cli_version(version_text: str) -> tuple[int, int, int] | None:
    """Extracts (major, minor, patch) integer tuple from version string."""
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_text)
    if not match:
        return None
    try:
        return int(match.group(1)), int(match.group(2)), int(match.group(3))
    except ValueError:
        return None


def format_reset_countdown(seconds: float | int) -> str:
    """Formats epoch delta in seconds to human-readable reset countdown."""
    sec = int(seconds)
    if sec <= 60:
        return "now"

    days = sec // 86400
    rem = sec % 86400
    hours = rem // 3600
    mins = (rem % 3600) // 60

    if days > 0:
        if hours > 0:
            return f"{days}d {hours}h"
        return f"{days}d"
    if hours > 0:
        if mins > 0:
            return f"{hours}h {mins}m"
        return f"{hours}h"
    return f"{mins}m"


def stdout_shows_model_turn(stdout: str) -> bool:
    """Scans stdout lines for evidence of an accidental model conversation turn.

    If agy does not support /usage, print mode treats it as a prompt, spending user quota.
    A real command has empty conversation_id and num_turns: 0.
    """
    for line in stdout.splitlines():
        trimmed = line.strip()
        if not trimmed.startswith("{"):
            continue
        try:
            payload = json.loads(trimmed)
            if not isinstance(payload, dict):
                continue
            turns = payload.get("num_turns")
            if isinstance(turns, (int, float)) and turns > 0:
                return True
            conv_id = payload.get("conversation_id")
            if isinstance(conv_id, str) and len(conv_id.strip()) > 0:
                return True
        except (json.JSONDecodeError, ValueError):
            continue
    return False


def parse_usage_stdout(stdout: str, now: float | None = None) -> QuotaSnapshot | None:
    """Parses raw stdout from `agy -p /usage --output-format json` into QuotaSnapshot."""
    current_time = time.time() if now is None else now

    for line in stdout.splitlines():
        trimmed = line.strip()
        if not trimmed.startswith("{"):
            continue
        try:
            envelope = json.loads(trimmed)
        except (json.JSONDecodeError, ValueError):
            continue

        if not isinstance(envelope, dict):
            continue
        if envelope.get("status") != "SUCCESS":
            continue

        cmd = envelope.get("command")
        if not isinstance(cmd, dict) or cmd.get("name") != "usage":
            continue

        data = cmd.get("data")
        if not isinstance(data, dict):
            continue

        groups = data.get("groups")
        if not isinstance(groups, list):
            continue

        parsed_buckets: list[QuotaBucket] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_name = str(group.get("name") or "").strip()
            raw_buckets = group.get("buckets")
            if not group_name or not isinstance(raw_buckets, list):
                continue

            # Filter out disabled buckets
            enabled_raw = [
                b for b in raw_buckets
                if isinstance(b, dict) and not b.get("disabled")
            ]
            total_enabled = len(enabled_raw)

            for b in enabled_raw:
                b_id = str(b.get("id") or "").strip()
                if not b_id:
                    continue

                frac = b.get("remaining_fraction")
                if not isinstance(frac, (int, float)) or math.isnan(frac) or math.isinf(frac):
                    continue

                remaining = float(frac)
                used_pct = min(100, max(0, round((1.0 - remaining) * 100)))

                b_name = str(b.get("name") or "").strip()
                if total_enabled <= 1 or not b_name:
                    label = group_name
                else:
                    label = f"{group_name} · {b_name}"

                window = str(b.get("window") or "").strip() or None

                resets_at: float | None = None
                resets_in: str | None = None
                reset_time_str = b.get("reset_time")
                if isinstance(reset_time_str, str) and reset_time_str.strip():
                    try:
                        clean_ts = reset_time_str.replace("Z", "+00:00")
                        dt = datetime.fromisoformat(clean_ts)
                        resets_at = dt.timestamp()
                        resets_in = format_reset_countdown(max(0.0, resets_at - current_time))
                    except (ValueError, TypeError, OSError):
                        pass

                parsed_buckets.append(
                    QuotaBucket(
                        id=b_id,
                        group=group_name,
                        name=b_name,
                        label=label,
                        window=window,
                        used_percent=used_pct,
                        remaining_fraction=remaining,
                        resets_at=resets_at,
                        resets_in=resets_in,
                    )
                )

        if not parsed_buckets:
            return None

        # Build summary for the most constrained weekly window
        summary: dict[str, Any] | None = None
        weekly_buckets = [b for b in parsed_buckets if b.window == "weekly"]
        if weekly_buckets:
            most_constrained_weekly = max(weekly_buckets, key=lambda b: b.used_percent)
            summary = {
                "weekly": {
                    "name": "Semanal",
                    "used_percent": most_constrained_weekly.used_percent,
                    "remaining_fraction": most_constrained_weekly.remaining_fraction,
                    "resets_at": most_constrained_weekly.resets_at,
                    "resets_in": most_constrained_weekly.resets_in,
                }
            }

        return QuotaSnapshot(
            status="ok",
            buckets=parsed_buckets,
            description=data.get("description") if isinstance(data.get("description"), str) else None,
            updated_at=current_time,
            error=None,
            summary=summary,
        )

    return None


class AgyCliQuotaProvider:
    """Thread-safe QuotaProvider reading quota from Antigravity CLI."""

    def __init__(
        self,
        command: str = "agy",
        runner: Callable[..., Any] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = 60.0,
        fallback_paths: list[Path] | None = None,
        is_file_fn: Callable[[Path], bool] | None = None,
        is_executable_fn: Callable[[Path], bool] | None = None,
    ) -> None:
        self.command = command
        self.runner = runner
        self.which = which
        self.clock = clock
        self.ttl_seconds = ttl_seconds
        self.fallback_paths = fallback_paths if fallback_paths is not None else [
            Path.home() / ".local" / "bin" / "agy",
            Path("/usr/local/bin/agy"),
            Path("/opt/homebrew/bin/agy"),
        ]
        self.is_file_fn = is_file_fn if is_file_fn is not None else (lambda p: p.is_file())
        self.is_executable_fn = is_executable_fn if is_executable_fn is not None else (lambda p: os.access(p, os.X_OK))

        self._lock = threading.Lock()
        self._cached_snapshot: QuotaSnapshot | None = None
        self._unsupported_latched: bool = False

    def _resolve_binary(self) -> str | None:
        """Finds absolute path to agy binary via which or fallback directories."""
        resolved = self.which(self.command)
        if resolved:
            return resolved

        for fallback in self.fallback_paths:
            try:
                if self.is_file_fn(fallback) and self.is_executable_fn(fallback):
                    return str(fallback)
            except (OSError, PermissionError):
                continue
        return None

    def fetch(self, force: bool = False) -> QuotaSnapshot:
        """Retrieves quota snapshot with single-flight locking, TTL caching, and error safety."""
        with self._lock:
            now = self.clock()

            if self._unsupported_latched:
                return QuotaSnapshot(
                    status="unavailable",
                    updated_at=now,
                    error="Antigravity usage is disabled: CLI previously answered as prompt and spent quota. Update `agy`.",
                )

            if (
                not force
                and self._cached_snapshot is not None
                and (now - self._cached_snapshot.updated_at) < self.ttl_seconds
            ):
                return self._cached_snapshot

            binary = self._resolve_binary()
            if not binary:
                return QuotaSnapshot(
                    status="unavailable",
                    updated_at=now,
                    error=f"Antigravity CLI ('{self.command}') not found on system PATH or default locations.",
                )

            # Check agy version to guarantee /usage does not consume a model turn
            try:
                ver_res = self.runner(
                    [binary, "--version"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5.0,
                )
                ver_text = (ver_res.stdout or "") + " " + (ver_res.stderr or "")
                parsed_ver = parse_cli_version(ver_text)
                if not parsed_ver or parsed_ver < MIN_USAGE_VERSION:
                    found_str = f"found {parsed_ver[0]}.{parsed_ver[1]}.{parsed_ver[2]}" if parsed_ver else "unreadable version"
                    return QuotaSnapshot(
                        status="unavailable",
                        updated_at=now,
                        error=f"Antigravity usage requires agy 1.1.11 or newer ({found_str}). Update the agy CLI to track quota safely.",
                    )
            except Exception as exc:
                return QuotaSnapshot(
                    status="unavailable",
                    updated_at=now,
                    error=f"Failed to check agy version: {exc}",
                )

            # Execute /usage command
            # IMPORTANT: NEVER pass --disable-slash-commands here!
            # That flag prevents agy from recognizing /usage as a slash command,
            # treating it as a model prompt and consuming paid quota!
            cmd_args = [binary, "-p", "/usage", "--output-format", "json", "--print-timeout", "20s"]
            try:
                run_res = self.runner(
                    cmd_args,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30.0,
                )
            except subprocess.TimeoutExpired:
                return self._handle_failure(now, "Antigravity CLI timed out after 30s while reading quota.")
            except Exception as exc:
                return self._handle_failure(now, f"Failed to execute agy usage command: {exc}")

            raw_out = run_res.stdout or ""
            raw_err = run_res.stderr or ""
            combined_out = raw_out + "\n" + raw_err

            # Parse reading
            reading = parse_usage_stdout(raw_out, now=now)
            if reading is not None:
                self._cached_snapshot = reading
                return reading

            # Check if this was an accidental model turn
            if stdout_shows_model_turn(raw_out):
                self._unsupported_latched = True
                return QuotaSnapshot(
                    status="unavailable",
                    updated_at=now,
                    error="Antigravity usage is disabled: CLI answered as prompt and spent quota. Update `agy`.",
                )

            # Heuristics for signed-out state
            lowered = combined_out.lower()
            if "not logged in" in lowered or "sign in" in lowered or "login" in lowered:
                return QuotaSnapshot(
                    status="unavailable",
                    updated_at=now,
                    error="Antigravity is not logged in. Sign in with `agy` to view quota.",
                )

            err_msg = f"Failed to parse Antigravity quota output (exit {run_res.returncode})."
            return self._handle_failure(now, err_msg)

    def _handle_failure(self, now: float, error_msg: str) -> QuotaSnapshot:
        """Handles failures with stale-on-error preservation when possible."""
        if self._cached_snapshot is not None and self._cached_snapshot.status == "ok":
            # Return stale snapshot with warning attached
            return QuotaSnapshot(
                status="ok",
                buckets=self._cached_snapshot.buckets,
                description=self._cached_snapshot.description,
                updated_at=self._cached_snapshot.updated_at,
                error=f"Warning: using cached quota ({error_msg})",
                summary=self._cached_snapshot.summary,
            )
        return QuotaSnapshot(
            status="error",
            updated_at=now,
            error=error_msg,
        )
