"""Antigravity model availability discovery for client setup presets.

Client configurations written by ``setup-*`` list the models a user can pick.
Listing a model the Antigravity backend does not serve for the current account
creates picker entries that always fail upstream, so the write path consults the
live catalog (``fetchAvailableModels``) and keeps only servable models.

Network access stays out of the configurators: ``fetch_agy_available_models`` is
called by the CLI layer, which passes the resulting id set into ``setup()``.
"""

from collections.abc import Iterable
from typing import TypeVar

T = TypeVar("T")


def fetch_agy_available_models(timeout: float = 15.0) -> set[str] | None:
    """Queries the Antigravity catalog for models servable on this account.

    Args:
        timeout: Upstream timeout in seconds for each catalog call.

    Returns:
        Set of upstream model ids, or None when availability could not be
        determined (no credentials, offline, upstream failure). None means
        "unknown": callers must not filter on it.
    """
    try:  # Imported lazily so importing setup modules stays side-effect free.
        from bridge.auth import KeychainTokenProvider
        from bridge.client import CloudCodeClient

        client = CloudCodeClient(KeychainTokenProvider(), timeout=timeout)
        project = client.load_code_assist().get("project")
        if not project:
            return None
        ids = {
            str(model.get("id"))
            for model in client.fetch_available_models(project)
            if isinstance(model, dict) and model.get("id")
        }
        return ids or None
    except Exception:
        return None


def split_by_availability(
    entries: Iterable[tuple[str, T]],
    available_models: set[str] | None,
) -> tuple[list[tuple[str, T]], list[str]]:
    """Splits (model_id, entry) pairs into servable pairs and skipped ids.

    Args:
        entries: Ordered (model_id, entry) pairs for one provider block.
        available_models: Catalog ids, or None when availability is unknown.

    Returns:
        tuple of (servable_pairs, skipped_model_ids), both preserving the input
        order. When availability is unknown every pair is kept and nothing is
        reported as skipped. Callers reshape the pairs as their client expects
        (a list of entries, or a dict keyed by model id).
    """
    pairs = list(entries)
    if available_models is None:
        return pairs, []

    kept: list[tuple[str, T]] = []
    skipped: list[str] = []
    for model_id, entry in pairs:
        if model_id in available_models:
            kept.append((model_id, entry))
        else:
            skipped.append(model_id)
    return kept, skipped



