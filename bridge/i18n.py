"""Internationalization (i18n) module for Antigravity Model Bridge.

Provides bilingual locale detection (EN / ES), message translation,
and affirmative choice parsing.
Zero external dependencies: pure Python standard library.
"""

from __future__ import annotations

import os
import re
from typing import Any

_current_locale: str | None = None


def detect_locale() -> str:
    """Detects system or configured locale.

    Checks AGY_LANG, LC_ALL, LC_MESSAGES, and LANG in priority order.
    Returns 'es' if language starts with 'es' (case-insensitive), otherwise 'en'.
    """
    for var in ("AGY_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "").strip()
        if val:
            if val.lower().startswith("es"):
                return "es"
            return "en"
    return "en"


def get_locale() -> str:
    """Returns the effective active locale ('en' or 'es')."""
    global _current_locale
    if _current_locale is not None:
        return _current_locale
    return detect_locale()


def set_locale(lang: str | None) -> None:
    """Sets a global locale override ('en', 'es'), or None to use system detection."""
    global _current_locale
    if lang is None:
        _current_locale = None
    elif lang.strip().lower().startswith("es"):
        _current_locale = "es"
    else:
        _current_locale = "en"


def is_yes(choice: str | None) -> bool:
    """Returns True if the choice represents an affirmative confirmation in EN or ES.

    Accepts 'y', 'yes', 's', 'si', 'sí' (case-insensitive, whitespace-trimmed).
    """
    if not isinstance(choice, str):
        return False
    normalized = choice.strip().lower()
    return normalized in ("y", "yes", "s", "si", "sí")


def parse_accept_language(header: str | None) -> str:
    """Parses an HTTP Accept-Language header and returns 'es' or 'en'.

    Evaluates language tags and quality values (q-factors).
    Returns 'es' if Spanish has higher priority, otherwise defaults to 'en'.
    """
    if not header or not isinstance(header, str):
        return "en"

    items: list[tuple[float, int, str]] = []
    for idx, part in enumerate(header.split(",")):
        part = part.strip()
        if not part:
            continue
        q = 1.0
        lang = part
        if ";" in part:
            pieces = part.split(";", 1)
            lang = pieces[0].strip()
            for param in pieces[1].split(";"):
                param = param.strip()
                if param.startswith("q="):
                    try:
                        q = float(param[2:])
                    except ValueError:
                        pass
        items.append((q, -idx, lang.lower()))

    # Sort descending by q factor, preserving original order on tie
    items.sort(reverse=True)
    for _, _, lang in items:
        if lang.startswith("es"):
            return "es"
        if lang.startswith("en"):
            return "en"
    return "en"


TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        # Daemon lifecycle
        "daemon_running_bg": "✔ AGY Model Bridge running in background (PID {pid})",
        "daemon_dashboard_url": "➜ Dashboard: {url}{browser_hint}",
        "daemon_stop_hint": "➜ To stop the service: {prog_base} stop",
        "daemon_already_running": "AGY Model Bridge is already running{pid_str}",
        "daemon_start_failed": "Failed to start daemon",
        "daemon_stopped": "✔ AGY Model Bridge stopped{pid_str}",
        "daemon_not_running": "AGY Model Bridge is not running.",
        "daemon_browser_opened": " (opened in browser)",
        "status_active": "✔ Status: Active{pid_str}",
        "status_address": "➜ Address: {url}",
        "status_models": "➜ Available models: {count}",
        "status_auth": "➜ Keychain Authentication: {status}",
        "status_stopped": "Status: Stopped",
        "status_start_hint": "Run '{prog_base} start' to launch the background service.",
        "dashboard_not_active": "Notice: The bridge does not appear to be active at {url}",
        "dashboard_opening": "Opening dashboard at {url}...",
        # Setup
        "setup_backup_label": "Backup: {path}",
        "setup_claude_success": "Claude Code configured successfully at {target}\n",
        "setup_claude_auto_read": "Claude Code will read this configuration automatically.",
        "setup_claude_run_hint": "Run 'claude' to start coding with Gemini 3.8 Flash · high (1M context).",
        "setup_codex_success": "Codex CLI configured successfully at {target}\n",
        "setup_codex_auto_read": "Codex CLI will read this configuration automatically.",
        "setup_codex_run_hint": "Run 'codex' to start coding with Gemini 3.8 Flash · high (1M context).",
        "setup_hermes_success": "Hermes Agent configured successfully at {target}\n",
        "setup_hermes_auto_read": "Hermes Agent will read this configuration automatically.",
        "setup_hermes_run_hint": "Run 'hermes' or open Hermes Desktop to start chatting.",
        # Restore
        "restore_restored_from": "Restored configuration from: {name}",
        "restore_client_ready": "{client_name} ready at {target}",
        "restore_no_backups": "No backups found for {client_name} in {parent}",
        "restore_available_title": "\nAvailable backups for {client_name}:",
        "restore_immediate_prev": "<-- Immediate previous",
        "restore_prompt": "\nEnter a number ({range_str}), press Enter for [1], or 'q' to cancel: ",
        "restore_cancelled": "Operation cancelled.",
        "restore_invalid_choice": "Invalid choice.",
        # Uninstall
        "uninstall_confirm_prompt": "Are you sure you want to uninstall AGY Model Bridge? [{choice}]: ",
        "uninstall_cancelled": "Uninstall operation cancelled.",
        "uninstall_success": "✔ AGY Model Bridge uninstalled successfully.",
        "uninstall_daemon_stopped": "  - Background service stopped.",
        "uninstall_binaries_removed": "  - Binaries removed: {binaries}",
        "uninstall_daemon_dir_removed": "  - Directory ~/.agy-bridge removed.",
        "uninstall_claude_restored": "  - Claude Code configuration restored.",
        "uninstall_codex_restored": "  - Codex CLI configuration restored.",
        "uninstall_hermes_restored": "  - Hermes Agent configuration restored.",
        "uninstall_backups_purged": "  - Backups history purged.",
        # Update
        "update_success": "✔ Repository updated to version v{ver}.",
        "update_daemon_restarted": "✔ Background service restarted with the new code.",
        "update_already_latest": "✔ You already have the latest version (v{ver}).",
        "update_failed": "Failed to update repository",
        "update_not_git_repo": "Directory is not a valid Git repository: {target_dir}",
        "update_git_not_found": "Command 'git' not found in system.",
        "update_git_error": "Error running git pull: {exc}",
        "update_up_to_date": "Repository is already up to date.",
        "update_completed": "Repository updated successfully.",
        # Common / CLI descriptions
        "cli_description": "Antigravity Model Bridge - Local AI Gateway",
        "cli_help_port": "Gateway port (default: 24980)",
        "cli_help_host": "Host address to bind server (default: 127.0.0.1)",
        "cli_help_no_open": "Do not open web browser automatically",
        "cli_help_project": "Google Cloud project ID override",
        "cli_help_base_url": "Upstream API base URL override",
        "cli_help_lang": "Language code override ('en' or 'es')",
    },
    "es": {
        # Daemon lifecycle
        "daemon_running_bg": "✔ AGY Model Bridge corriendo en segundo plano (PID {pid})",
        "daemon_dashboard_url": "➜ Dashboard: {url}{browser_hint}",
        "daemon_stop_hint": "➜ Para detener el servicio: {prog_base} stop",
        "daemon_already_running": "AGY Model Bridge ya está corriendo{pid_str}",
        "daemon_start_failed": "Fallo al iniciar el daemon",
        "daemon_stopped": "✔ AGY Model Bridge detenido{pid_str}",
        "daemon_not_running": "AGY Model Bridge no está corriendo.",
        "daemon_browser_opened": " (abierto en el navegador)",
        "status_active": "✔ Estado: Activo{pid_str}",
        "status_address": "➜ Dirección: {url}",
        "status_models": "➜ Modelos disponibles: {count}",
        "status_auth": "➜ Autenticación Keychain: {status}",
        "status_stopped": "Estado: Detenido",
        "status_start_hint": "Ejecute '{prog_base} start' para iniciar el servicio en segundo plano.",
        "dashboard_not_active": "Aviso: El bridge no parece estar activo en {url}",
        "dashboard_opening": "Abriendo dashboard en {url}...",
        # Setup
        "setup_backup_label": "Backup: {path}",
        "setup_claude_success": "Claude Code configurado correctamente en {target}\n",
        "setup_claude_auto_read": "Claude Code leerá esta configuración automáticamente.",
        "setup_claude_run_hint": "Ejecutá 'claude' para empezar a programar con Gemini 3.8 Flash · high (1M de contexto).",
        "setup_codex_success": "Codex CLI configurado correctamente en {target}\n",
        "setup_codex_auto_read": "Codex CLI leerá esta configuración automáticamente.",
        "setup_codex_run_hint": "Ejecutá 'codex' para empezar a programar con Gemini 3.8 Flash · high (1M de contexto).",
        "setup_hermes_success": "Hermes Agent configurado correctamente en {target}\n",
        "setup_hermes_auto_read": "Hermes Agent leerá esta configuración automáticamente.",
        "setup_hermes_run_hint": "Ejecutá 'hermes' o abrí Hermes Desktop para empezar a chatear.",
        # Restore
        "restore_restored_from": "Restaurada configuración desde: {name}",
        "restore_client_ready": "{client_name} listo en {target}",
        "restore_no_backups": "No se encontraron backups para {client_name} en {parent}",
        "restore_available_title": "\nBackups disponibles para {client_name}:",
        "restore_immediate_prev": "<-- Anterior inmediata",
        "restore_prompt": "\nIngrese un número ({range_str}), presione Enter para [1], o 'q' para cancelar: ",
        "restore_cancelled": "Operación cancelada.",
        "restore_invalid_choice": "Opción inválida.",
        # Uninstall
        "uninstall_confirm_prompt": "¿Estás seguro de que deseas desinstalar AGY Model Bridge? [{choice}]: ",
        "uninstall_cancelled": "Operación de desinstalación cancelada.",
        "uninstall_success": "✔ AGY Model Bridge desinstalado correctamente.",
        "uninstall_daemon_stopped": "  - Servicio en segundo plano detenido.",
        "uninstall_binaries_removed": "  - Binarios eliminados: {binaries}",
        "uninstall_daemon_dir_removed": "  - Directorio ~/.agy-bridge eliminado.",
        "uninstall_claude_restored": "  - Configuración de Claude Code restaurada.",
        "uninstall_codex_restored": "  - Configuración de Codex CLI restaurada.",
        "uninstall_hermes_restored": "  - Configuración de Hermes Agent restaurada.",
        "uninstall_backups_purged": "  - Historial de backups purgado.",
        # Update
        "update_success": "✔ Repositorio actualizado a la versión v{ver}.",
        "update_daemon_restarted": "✔ Servicio en segundo plano reiniciado con el nuevo código.",
        "update_already_latest": "✔ Ya tenés la versión más reciente (v{ver}).",
        "update_failed": "Fallo al actualizar el repositorio",
        "update_not_git_repo": "Directorio no es un repositorio Git válido: {target_dir}",
        "update_git_not_found": "Comando 'git' no encontrado en el sistema.",
        "update_git_error": "Error ejecutando git pull: {exc}",
        "update_up_to_date": "Repositorio ya está actualizado.",
        "update_completed": "Repositorio actualizado correctamente.",
        # Common / CLI descriptions
        "cli_description": "Antigravity Model Bridge - Gateway local de IA",
        "cli_help_port": "Puerto del gateway (por defecto: 24980)",
        "cli_help_host": "Dirección de host para enlazar el servidor (por defecto: 127.0.0.1)",
        "cli_help_no_open": "No abrir el navegador automáticamente",
        "cli_help_project": "Sobrescribir el ID de proyecto de Google Cloud",
        "cli_help_base_url": "Sobrescribir la URL base de la API upstream",
        "cli_help_lang": "Sobrescribir código de idioma ('en' o 'es')",
    },
}


class _SafeDict(dict):
    """Dictionary that leaves missing format keys intact as {key}."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def t(key: str, lang: str | None = None, **kwargs: Any) -> str:
    """Translates a message key into the requested or detected language.

    Falls back to English if missing from the requested language,
    and returns key if missing from all dictionaries.
    Formats kwargs safely into the string.
    """
    effective_lang = lang if lang is not None else get_locale()
    if effective_lang.strip().lower().startswith("es"):
        primary_lang = "es"
    else:
        primary_lang = "en"

    template = TRANSLATIONS.get(primary_lang, {}).get(key)
    if template is None:
        template = TRANSLATIONS.get("en", {}).get(key, key)

    if not kwargs:
        return template

    try:
        return template.format_map(_SafeDict(**kwargs))
    except Exception:
        return template
