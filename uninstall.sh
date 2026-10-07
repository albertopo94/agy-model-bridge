#!/usr/bin/env bash
# AGY Model Bridge - Zero-dependency uninstaller for macOS & Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/albertopo94/agy-model-bridge/main/uninstall.sh | bash

set -e

STATE_DIR="${AGY_BRIDGE_STATE_DIR:-$HOME/.agy-bridge}"
CORE_DIR="${AGY_BRIDGE_CORE_DIR:-${AGY_BRIDGE_DIR:-$STATE_DIR/core}}"
BIN_DIR="${AGY_BRIDGE_BIN:-$HOME/.local/bin}"

BOLD="\033[1m"
GREEN="\033[32m"
BLUE="\033[34m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

# Language detection (default English, Spanish if es/ES)
IS_ES=0
case "${AGY_LANG:-${LC_ALL:-${LANG:-}}}" in
    es*|ES*) IS_ES=1 ;;
    *) IS_ES=0 ;;
esac

for arg in "$@"; do
    case "$arg" in
        --lang=es*|--lang=ES*) IS_ES=1 ;;
        --lang=en*|--lang=EN*) IS_ES=0 ;;
    esac
done

if [ "$IS_ES" = "1" ]; then
    echo -e "${BOLD}${BLUE}==> Desinstalando AGY Model Bridge...${RESET}"
else
    echo -e "${BOLD}${BLUE}==> Uninstalling AGY Model Bridge...${RESET}"
fi

UNINSTALL_EXECUTED=0
RESTORED_CONFIGS=0

# 1. First, invoke Python uninstaller to safely stop daemon with PID verification and restore configs
if command -v agy-bridge >/dev/null 2>&1; then
    if [ "$IS_ES" = "1" ]; then
        echo -e "Ejecutando desinstalador seguro de AGY Model Bridge..."
    else
        echo -e "Running safe AGY Model Bridge uninstaller..."
    fi
    if agy-bridge uninstall --yes "$@"; then
        UNINSTALL_EXECUTED=1
        RESTORED_CONFIGS=1
    fi
elif [ -d "$CORE_DIR" ] && command -v python3 >/dev/null 2>&1; then
    if [ "$IS_ES" = "1" ]; then
        echo -e "Ejecutando desinstalador seguro desde ${CORE_DIR}..."
    else
        echo -e "Running safe uninstaller from ${CORE_DIR}..."
    fi
    if PYTHONPATH="$CORE_DIR:$PYTHONPATH" python3 -m bridge uninstall --yes "$@"; then
        UNINSTALL_EXECUTED=1
        RESTORED_CONFIGS=1
    fi
elif [ -d "$(pwd)/bridge" ] && command -v python3 >/dev/null 2>&1; then
    if [ "$IS_ES" = "1" ]; then
        echo -e "Ejecutando desinstalador seguro desde el directorio actual..."
    else
        echo -e "Running safe uninstaller from current directory..."
    fi
    if PYTHONPATH="$(pwd):$PYTHONPATH" python3 -m bridge uninstall --yes "$@"; then
        UNINSTALL_EXECUTED=1
        RESTORED_CONFIGS=1
    fi
fi

# 2. Fallback daemon stop and cleanup if Python uninstaller was unavailable
if [ "$UNINSTALL_EXECUTED" = "0" ]; then
    PID_FILE="$STATE_DIR/bridge.pid"
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE" 2>/dev/null || true)
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            CMDLINE=$(ps -p "$PID" -o command= 2>/dev/null || true)
            case "$CMDLINE" in
                *bridge*|*agy-bridge*)
                    if [ "$IS_ES" = "1" ]; then
                        echo -e "Deteniendo el daemon de AGY Model Bridge (PID $PID)..."
                    else
                        echo -e "Stopping AGY Model Bridge daemon (PID $PID)..."
                    fi
                    kill "$PID" 2>/dev/null || true
                    for _ in {1..30}; do
                        if ! kill -0 "$PID" 2>/dev/null; then
                            break
                        fi
                        sleep 0.1
                    done
                    if kill -0 "$PID" 2>/dev/null; then
                        kill -9 "$PID" 2>/dev/null || true
                    fi
                    ;;
                *)
                    if [ "$IS_ES" = "1" ]; then
                        echo -e "${YELLOW}Advertencia: El proceso PID $PID no corresponde a AGY Bridge. Omitiendo kill.${RESET}"
                    else
                        echo -e "${YELLOW}Warning: Process PID $PID does not match AGY Bridge. Skipping kill.${RESET}"
                    fi
                    ;;
            esac
        fi
        rm -f "$PID_FILE"
    fi
    rm -f "$STATE_DIR/bridge.json" "$STATE_DIR/bridge.lock"

    # Remove launcher scripts
    rm -f "$BIN_DIR/agy-bridge"
    rm -f "$BIN_DIR/agy-model-bridge"

    # Remove state directory
    if [ -d "$STATE_DIR" ]; then
        rm -rf "$STATE_DIR"
    fi
    # Remove core directory only if distinct, not current dir, and not home
    if [ -d "$CORE_DIR" ] && [ "$CORE_DIR" != "$STATE_DIR" ] && [ "$CORE_DIR" != "$(pwd)" ] && [ "$CORE_DIR" != "$HOME" ]; then
        rm -rf "$CORE_DIR"
    fi
fi

echo ""
if [ "$IS_ES" = "1" ]; then
    echo -e "${GREEN}${BOLD}✔ AGY Model Bridge desinstalado correctamente!${RESET}"
    if [ "$RESTORED_CONFIGS" = "1" ]; then
        echo -e "  Configuraciones de clientes restauradas a su estado previo."
    fi
    echo -e "  Binarios en ${BIN_DIR} y directorio ${STATE_DIR} eliminados."
    echo ""
else
    echo -e "${GREEN}${BOLD}✔ AGY Model Bridge uninstalled successfully!${RESET}"
    if [ "$RESTORED_CONFIGS" = "1" ]; then
        echo -e "  Client configurations restored to their previous state."
    fi
    echo -e "  Binaries in ${BIN_DIR} and directory ${STATE_DIR} removed."
    echo ""
fi
