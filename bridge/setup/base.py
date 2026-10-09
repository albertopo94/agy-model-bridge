"""Base classes and registry for client configurators."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from bridge.setup.common import list_backups


class ConfigPath(Path):
    """Path subclass that carries an optional backup_path attribute."""
    backup_path: Path | None = None


class ClientConfigurator(ABC):
    """Abstract base class (Strategy) for client configuration management."""

    name: str = ""
    display_name: str = ""

    @property
    @abstractmethod
    def default_config_path(self) -> Path:
        """Default filesystem path for this client's configuration file."""
        pass

    def get_config_path(self, custom_path: Path | None = None) -> Path:
        """Returns custom_path if provided, else default_config_path."""
        if custom_path is not None:
            return Path(custom_path)
        return self.default_config_path

    @abstractmethod
    def is_configured(self, config_path: Path | None = None) -> bool:
        """Returns True if AGY configuration settings or blocks are present in the target config."""
        pass

    @abstractmethod
    def setup(
        self,
        base_url: str | None = None,
        model: str = "gemini-3.8-flash-high",
        config_path: Path | None = None,
        **kwargs: Any,
    ) -> Path | dict[str, Any]:
        """Configures the client file to point to AGY model bridge."""
        pass

    @abstractmethod
    def restore(
        self,
        config_path: Path | None = None,
        backup_path: Path | None = None,
        **kwargs: Any,
    ) -> bool:
        """Restores the client configuration from a backup or performs surgical removal."""
        pass

    def list_backups(self, config_path: Path | None = None) -> list[Path]:
        """Lists historical backup files for this client, sorted by mtime descending."""
        target = self.get_config_path(config_path)
        return list_backups(target)

    def purge_backups(self, config_path: Path | None = None) -> int:
        """Deletes all historical backup files for this client. Returns number of purged files."""
        target = self.get_config_path(config_path)
        purged = 0
        for b in self.list_backups(target):
            try:
                b.unlink()
                purged += 1
            except OSError:
                pass
        return purged


_CONFIGURATORS: dict[str, ClientConfigurator] = {}
CLIENT_CONFIGURATORS = _CONFIGURATORS


def register_configurator(configurator: ClientConfigurator) -> None:
    """Registers a client configurator into the global registry."""
    CLIENT_CONFIGURATORS[configurator.name] = configurator


def get_configurator(name: str) -> ClientConfigurator:
    """Retrieves a client configurator by name from the registry."""
    if name not in CLIENT_CONFIGURATORS:
        raise KeyError(f"Unknown client configurator: '{name}'")
    return CLIENT_CONFIGURATORS[name]


def list_configurators() -> list[ClientConfigurator]:
    """Returns a list of all registered client configurators."""
    seen: set[str] = set()
    result: list[ClientConfigurator] = []
    for c in CLIENT_CONFIGURATORS.values():
        if c.name not in seen:
            seen.add(c.name)
            result.append(c)
    return result
