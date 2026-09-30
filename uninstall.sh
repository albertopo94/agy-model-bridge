#!/usr/bin/env bash
# AGY Model Bridge - Zero-dependency uninstaller for macOS & Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/albertopo94/agy-model-bridge/main/uninstall.sh | bash

set -e

DAEMON_DIR="${AGY_BRIDGE_DIR:-$HOME/.agy-bridge}"
BIN_DIR="${AGY_BRIDGE_BIN:-$HOME/.local/bin}"
PID_FILE="$DAEMON_DIR/bridge.pid"

BOLD="\033[1m"
GREEN="\033[32m"
BLUE="\033[34m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

echo -e "${BOLD}${BLUE}==> Desinstalando AGY Model Bridge...${RESET}"

# 1. Stop background daemon if running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo -e "Deteniendo el daemon de AGY Model Bridge (PID $PID)..."
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
    fi
    rm -f "$PID_FILE"
fi

# 2. Invoke Python uninstall to restore client configurations
RESTORED_CONFIGS=0
if command -v agy-bridge >/dev/null 2>&1; then
    echo -e "Restaurando configuraciones de clientes..."
    agy-bridge uninstall --yes "$@" 2>/dev/null || true
    RESTORED_CONFIGS=1
elif [ -d "$DAEMON_DIR/core" ] && command -v python3 >/dev/null 2>&1; then
    echo -e "Restaurando configuraciones de clientes..."
    PYTHONPATH="$DAEMON_DIR/core:$PYTHONPATH" python3 -m bridge uninstall --yes "$@" 2>/dev/null || true
    RESTORED_CONFIGS=1
elif [ -d "$(pwd)/bridge" ] && command -v python3 >/dev/null 2>&1; then
    echo -e "Restaurando configuraciones de clientes..."
    PYTHONPATH="$(pwd):$PYTHONPATH" python3 -m bridge uninstall --yes "$@" 2>/dev/null || true
    RESTORED_CONFIGS=1
fi

# 3. Remove launcher binaries
echo -e "Eliminando binarios y scripts..."
rm -f "$BIN_DIR/agy-bridge"
rm -f "$BIN_DIR/agy-model-bridge"

# 4. Remove daemon directory
if [ -d "$DAEMON_DIR" ]; then
    echo -e "Eliminando directorio ${DAEMON_DIR}..."
    rm -rf "$DAEMON_DIR"
fi

echo ""
echo -e "${GREEN}${BOLD}✔ AGY Model Bridge desinstalado correctamente!${RESET}"
if [ "$RESTORED_CONFIGS" = "1" ]; then
    echo -e "  Configuraciones de Claude Code y Codex CLI restauradas a su estado previo."
fi
echo -e "  Binarios en ${BIN_DIR} y directorio ${DAEMON_DIR} eliminados."
echo ""
