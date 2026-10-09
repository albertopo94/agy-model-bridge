"""Configurator strategy and setup functions for Cursor."""

from pathlib import Path
from typing import Any, cast

from bridge.setup.base import ClientConfigurator, get_configurator
from bridge.setup.common import get_active_api_key


class CursorConfigurator(ClientConfigurator):
    """Configurator strategy for Cursor (guide-only)."""

    name = "cursor"
    display_name = "Cursor"

    @property
    def default_config_path(self) -> Path:
        return Path.home() / ".cursor"

    def is_configured(self, config_path: Path | None = None) -> bool:
        return False

    def setup(
        self,
        base_url: str | None = None,
        model: str = "gemini-3.8-flash-high",
        config_path: Path | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        port = kwargs.get("port")
        auth_token = kwargs.get("auth_token") or get_active_api_key()

        if base_url:
            resolved_url = base_url.rstrip("/")
            if not resolved_url.endswith("/v1"):
                resolved_url = f"{resolved_url}/v1"
        elif port is not None:
            resolved_url = f"http://127.0.0.1:{port}/v1"
        else:
            resolved_url = "http://127.0.0.1:24980/v1"

        model_names = [model] + [
            m
            for m in (
                "gemini-3.8-flash-high",
                "claude-sonnet-5-5-high",
                "claude-opus-5-5-high",
                "gemini-2.5-pro",
                "gemini-2.5-flash",
            )
            if m != model
        ]
        models_str = ", ".join(model_names)

        notes = [
            "Cursor routes requests through Cursor cloud servers.",
            "Localhost requires an HTTPS tunnel (e.g. Cloudflare Tunnel, ngrok, Tailscale) for Cursor cloud to reach your local bridge.",
            "Open Cursor Settings -> Models -> Enable Override OpenAI Base URL.",
            f"Set Base URL to: {resolved_url}",
            f"Set API Key to: {auth_token}",
            f"Add models: {models_str}",
        ]

        return {
            "url": resolved_url,
            "apiKey": auth_token,
            "model": model,
            "notes": notes,
        }

    def restore(
        self,
        config_path: Path | None = None,
        backup_path: Path | None = None,
        **kwargs: Any,
    ) -> bool:
        return False

    def list_backups(self, config_path: Path | None = None) -> list[Path]:
        return []

    def purge_backups(self, config_path: Path | None = None) -> int:
        return 0


def setup_cursor(
    base_url: str | None = None,
    port: int | None = None,
    model: str = "gemini-3.8-flash-high",
    lang: str = "en",
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Returns setup guide parameters for Cursor."""
    return cast(
        dict[str, Any],
        get_configurator("cursor").setup(
            base_url=base_url,
            port=port,
            model=model,
            lang=lang,
            auth_token=auth_token,
        ),
    )
