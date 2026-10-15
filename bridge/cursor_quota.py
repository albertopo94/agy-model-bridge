"""Cursor account usage and quota provider.

Zero external dependencies: pure standard library.
Reads session credentials via CursorAuthManager and queries https://cursor.com/api/usage-summary.
"""

from datetime import datetime, timezone
import json
import re
import threading
import time
from typing import Any
import urllib.error
import urllib.request

from bridge.cursor_auth import CursorAuthManager, CursorSession
from bridge.errors import AuthenticationError
from bridge.quota import (
    QuotaBucket,
    QuotaSnapshot,
    format_reset_countdown,
)

CURSOR_USAGE_SUMMARY_URL: str = "https://cursor.com/api/usage-summary"


def _parse_iso_timestamp(iso_str: str | None) -> float | None:
    """Parses an ISO 8601 timestamp string into epoch seconds."""
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        clean = iso_str.replace("Z", "+00:00")
        clean = re.sub(r"\.(\d{6})\d+", r".\1", clean)
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError, OSError):
        return None


def parse_cursor_usage_summary(data: dict[str, Any], now: float | None = None) -> QuotaSnapshot:
    """Parses response from https://cursor.com/api/usage-summary into QuotaSnapshot."""
    current_time = time.time() if now is None else now

    if not isinstance(data, dict):
        return QuotaSnapshot(
            status="error",
            error="Unexpected Cursor usage response: expected JSON object",
            updated_at=current_time,
        )

    # Must contain at least individualUsage or billingCycleEnd
    individual_usage = data.get("individualUsage")
    billing_cycle_end_raw = data.get("billingCycleEnd")

    if not isinstance(individual_usage, dict) and not billing_cycle_end_raw:
        return QuotaSnapshot(
            status="error",
            error="Unexpected Cursor usage structure: missing individualUsage and billingCycleEnd",
            updated_at=current_time,
        )

    membership_type = str(data.get("membershipType") or "free").lower()
    is_unlimited = bool(data.get("isUnlimited"))

    if is_unlimited:
        description = "Unlimited Plan"
    elif membership_type == "pro":
        description = "Pro Plan"
    elif membership_type == "enterprise":
        description = "Enterprise Plan"
    elif membership_type == "business":
        description = "Business Plan"
    elif membership_type == "free":
        description = "Free Tier"
    else:
        description = f"{membership_type.capitalize()} Plan"

    resets_at = _parse_iso_timestamp(billing_cycle_end_raw)
    resets_in = (
        format_reset_countdown(max(0.0, resets_at - current_time))
        if resets_at is not None
        else None
    )

    plan = individual_usage.get("plan", {}) if isinstance(individual_usage, dict) else {}
    buckets: list[QuotaBucket] = []

    if isinstance(plan, dict) and plan.get("enabled", True):
        # 1. Cursor Models (autoPercentUsed)
        auto_used = plan.get("autoPercentUsed", 0.0)
        if isinstance(auto_used, (int, float)):
            used_pct = min(100, max(0, round(float(auto_used))))
            rem_frac = max(0.0, min(1.0, 1.0 - (float(auto_used) / 100.0)))
            buckets.append(
                QuotaBucket(
                    id="cursor-models",
                    group="Cursor",
                    name="Cursor Models",
                    label="Cursor Models",
                    window="monthly",
                    used_percent=used_pct,
                    remaining_fraction=rem_frac,
                    resets_at=resets_at,
                    resets_in=resets_in,
                )
            )

        # 2. Other Models (apiPercentUsed)
        api_used = plan.get("apiPercentUsed", 0.0)
        if isinstance(api_used, (int, float)):
            used_pct = min(100, max(0, round(float(api_used))))
            rem_frac = max(0.0, min(1.0, 1.0 - (float(api_used) / 100.0)))
            buckets.append(
                QuotaBucket(
                    id="other-models",
                    group="Cursor",
                    name="Other Models",
                    label="Other Models",
                    window="monthly",
                    used_percent=used_pct,
                    remaining_fraction=rem_frac,
                    resets_at=resets_at,
                    resets_in=resets_in,
                )
            )

        # 3. Overall Plan (totalPercentUsed)
        total_used = plan.get("totalPercentUsed", 0.0)
        if isinstance(total_used, (int, float)):
            used_pct = min(100, max(0, round(float(total_used))))
            rem_frac = max(0.0, min(1.0, 1.0 - (float(total_used) / 100.0)))
            buckets.append(
                QuotaBucket(
                    id="plan",
                    group="Cursor",
                    name="Plan",
                    label="Plan",
                    window="monthly",
                    used_percent=used_pct,
                    remaining_fraction=rem_frac,
                    resets_at=resets_at,
                    resets_in=resets_in,
                )
            )

    # Optional On-Demand bucket if enabled and active
    on_demand = individual_usage.get("onDemand", {}) if isinstance(individual_usage, dict) else {}
    if isinstance(on_demand, dict) and on_demand.get("enabled"):
        od_used = on_demand.get("totalPercentUsed") or on_demand.get("used", 0)
        if isinstance(od_used, (int, float)):
            used_pct = min(100, max(0, round(float(od_used))))
            buckets.append(
                QuotaBucket(
                    id="on-demand",
                    group="Cursor",
                    name="On-demand",
                    label="On-demand",
                    window="monthly",
                    used_percent=used_pct,
                    remaining_fraction=max(0.0, 1.0 - (float(od_used) / 100.0)),
                    resets_at=resets_at,
                    resets_in=resets_in,
                )
            )

    summary = {
        "membership_type": membership_type,
        "is_unlimited": is_unlimited,
        "billing_cycle_start": data.get("billingCycleStart"),
        "billing_cycle_end": billing_cycle_end_raw,
    }

    return QuotaSnapshot(
        status="ok",
        buckets=buckets,
        description=description,
        updated_at=current_time,
        summary=summary,
    )


class CursorQuotaProvider:
    """Thread-safe QuotaProvider implementation for Cursor."""

    def __init__(
        self,
        auth_manager: CursorAuthManager | None = None,
        cache_ttl: float = 60.0,
        endpoint_url: str = CURSOR_USAGE_SUMMARY_URL,
    ) -> None:
        self.auth_manager = auth_manager or CursorAuthManager()
        self.cache_ttl = cache_ttl
        self.endpoint_url = endpoint_url
        self._cached_snapshot: QuotaSnapshot | None = None
        self._lock = threading.Lock()

    def fetch(self, force: bool = False) -> QuotaSnapshot:
        """Fetches quota snapshot from Cursor API or returns cached."""
        now = time.time()
        with self._lock:
            if (
                not force
                and self._cached_snapshot is not None
                and (now - self._cached_snapshot.updated_at) < self.cache_ttl
            ):
                return self._cached_snapshot

        # Fetch outside the lock so we don't block concurrent readers
        try:
            session = self.auth_manager.get_session(force_refresh=force)
        except AuthenticationError as exc:
            snapshot = QuotaSnapshot(
                status="unavailable",
                error=str(exc),
                updated_at=now,
            )
            with self._lock:
                self._cached_snapshot = snapshot
            return snapshot

        headers = {
            "Cookie": session.cookie,
            "Accept": "application/json",
            "Origin": "https://cursor.com",
            "Referer": "https://cursor.com/dashboard",
            "User-Agent": "Mozilla/5.0",
        }
        req = urllib.request.Request(self.endpoint_url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                body = resp.read().decode("utf-8")
                parsed_json = json.loads(body)
                snapshot = parse_cursor_usage_summary(parsed_json, now=now)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                self.auth_manager.invalidate()
                snapshot = QuotaSnapshot(
                    status="error",
                    error="Cursor session expired. Run `agent login` again.",
                    updated_at=now,
                )
            elif exc.code == 429:
                snapshot = self._handle_stale_or_error(
                    now, "Cursor usage is currently rate limited."
                )
            else:
                snapshot = self._handle_stale_or_error(
                    now, f"Cursor API request failed (HTTP {exc.code})."
                )
        except Exception as exc:
            snapshot = self._handle_stale_or_error(
                now, f"Failed to fetch Cursor usage: {exc}"
            )

        with self._lock:
            self._cached_snapshot = snapshot
        return snapshot

    def _handle_stale_or_error(self, now: float, error_msg: str) -> QuotaSnapshot:
        """Returns stale snapshot if available, otherwise an error snapshot."""
        with self._lock:
            if self._cached_snapshot is not None and self._cached_snapshot.status == "ok":
                # Return previous good snapshot with updated error note
                return QuotaSnapshot(
                    status="ok",
                    buckets=self._cached_snapshot.buckets,
                    description=self._cached_snapshot.description,
                    updated_at=self._cached_snapshot.updated_at,
                    error=error_msg,
                    summary=self._cached_snapshot.summary,
                )
        return QuotaSnapshot(
            status="error",
            error=error_msg,
            updated_at=now,
        )
