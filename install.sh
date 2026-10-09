#!/usr/bin/env bash
# AGY Model Bridge - Zero-dependency installer for macOS & Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/albertopo94/agy-model-bridge/main/install.sh | bash

set -e

REPO_URL="https://github.com/albertopo94/agy-model-bridge.git"
STATE_DIR="${AGY_BRIDGE_STATE_DIR:-$HOME/.agy-bridge}"
INSTALL_DIR="${AGY_BRIDGE_CORE_DIR:-${AGY_BRIDGE_DIR:-$STATE_DIR/core}}"
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
    echo -e "${BOLD}${BLUE}==> Instalando AGY Model Bridge...${RESET}"
else
    echo -e "${BOLD}${BLUE}==> Installing AGY Model Bridge...${RESET}"
fi

# 1. Check Python version (>= 3.10 required)
if ! command -v python3 >/dev/null 2>&1; then
    if [ "$IS_ES" = "1" ]; then
        echo -e "${RED}Error: python3 no está instalado. Se requiere Python 3.10 o superior.${RESET}"
    else
        echo -e "${RED}Error: python3 is not installed. Python 3.10 or higher is required.${RESET}"
    fi
    exit 1
fi

PYTHON_OK=$(python3 -c "import sys; print(1 if sys.version_info >= (3, 10) else 0)" 2>/dev/null || echo 0)
if [ "$PYTHON_OK" != "1" ]; then
    PYTHON_VER=$(python3 -V 2>&1)
    if [ "$IS_ES" = "1" ]; then
        echo -e "${RED}Error: $PYTHON_VER no soportado. Se requiere Python 3.10+.${RESET}"
    else
        echo -e "${RED}Error: $PYTHON_VER not supported. Python 3.10+ required.${RESET}"
    fi
    exit 1
fi

# 2. Check Git
if ! command -v git >/dev/null 2>&1; then
    if [ "$IS_ES" = "1" ]; then
        echo -e "${RED}Error: git no está instalado.${RESET}"
    else
        echo -e "${RED}Error: git is not installed.${RESET}"
    fi
    exit 1
fi

# 3. Clone or update repository
mkdir -p "$(dirname "$INSTALL_DIR")"
PINNED_VERSION="v0.20.0"
TARGET_REF="${AGY_BRIDGE_VERSION:-$PINNED_VERSION}"

if [ -d "$INSTALL_DIR/.git" ]; then
    if [ "$IS_ES" = "1" ]; then
        echo -e "Actualizando repositorio existente en ${INSTALL_DIR}..."
    else
        echo -e "Updating existing repository in ${INSTALL_DIR}..."
    fi
    git -C "$INSTALL_DIR" fetch --tags --quiet 2>/dev/null || true
    if [ -n "$TARGET_REF" ]; then
        if ! git -C "$INSTALL_DIR" checkout "$TARGET_REF" --quiet 2>/dev/null; then
            if [ "$IS_ES" = "1" ]; then
                echo -e "${RED}Error: No se pudo hacer checkout de la versión ${TARGET_REF} en ${INSTALL_DIR}.${RESET}"
            else
                echo -e "${RED}Error: Failed to checkout version ${TARGET_REF} in ${INSTALL_DIR}.${RESET}"
            fi
            exit 1
        fi
    else
        if ! git -C "$INSTALL_DIR" pull --quiet; then
            if [ "$IS_ES" = "1" ]; then
                echo -e "${RED}Error: Falló la actualización del repositorio en ${INSTALL_DIR}.${RESET}"
            else
                echo -e "${RED}Error: Failed to update existing repository in ${INSTALL_DIR}.${RESET}"
            fi
            exit 1
        fi
    fi
else
    if [ "$IS_ES" = "1" ]; then
        echo -e "Descargando en ${INSTALL_DIR}..."
    else
        echo -e "Downloading to ${INSTALL_DIR}..."
    fi
    if ! git clone --quiet "$REPO_URL" "$INSTALL_DIR"; then
        if [ "$IS_ES" = "1" ]; then
            echo -e "${RED}Error: Falló la clonación del repositorio en ${INSTALL_DIR}.${RESET}"
        else
            echo -e "${RED}Error: Failed to clone repository into ${INSTALL_DIR}.${RESET}"
        fi
        exit 1
    fi
    if [ -n "$TARGET_REF" ]; then
        if ! git -C "$INSTALL_DIR" checkout "$TARGET_REF" --quiet 2>/dev/null; then
            if [ "$IS_ES" = "1" ]; then
                echo -e "${RED}Error: No se pudo hacer checkout de la versión ${TARGET_REF} en ${INSTALL_DIR}.${RESET}"
            else
                echo -e "${RED}Error: Failed to checkout version ${TARGET_REF} in ${INSTALL_DIR}.${RESET}"
            fi
            exit 1
        fi
    fi
fi

# Write .agy-bridge-installed sentinel marker to authorize safe uninstallation
mkdir -p "$INSTALL_DIR"
printf "%s\n" "$TARGET_REF" > "$INSTALL_DIR/.agy-bridge-installed"
chmod 600 "$INSTALL_DIR/.agy-bridge-installed"

# 4. Create binary launcher wrapper in ~/.local/bin
mkdir -p "$STATE_DIR"
if [ "$INSTALL_DIR" != "$STATE_DIR/core" ]; then
    printf "%s\n" "$INSTALL_DIR" > "$STATE_DIR/.core_dir"
    chmod 600 "$STATE_DIR/.core_dir"
else
    rm -f "$STATE_DIR/.core_dir"
fi

mkdir -p "$BIN_DIR"
LAUNCHER="$BIN_DIR/agy-bridge"

cat <<'EOF' > "$LAUNCHER"
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${AGY_BRIDGE_STATE_DIR:-$HOME/.agy-bridge}"
if [ -z "$AGY_BRIDGE_CORE_DIR" ] && [ -f "$STATE_DIR/.core_dir" ]; then
    AGY_BRIDGE_CORE_DIR="$(cat "$STATE_DIR/.core_dir")"
fi
CORE_DIR="${AGY_BRIDGE_CORE_DIR:-${AGY_BRIDGE_DIR:-$STATE_DIR/core}}"
export PYTHONPATH="$CORE_DIR:$PYTHONPATH"
exec python3 -u -c "import sys, os; core = sys.argv.pop(1); cwd = os.getcwd(); sys.path = [p for p in sys.path if p not in ('', cwd)]; sys.path.insert(0, core); from bridge.__main__ import main; sys.exit(main())" "$CORE_DIR" "$@"
EOF

chmod 755 "$LAUNCHER"
ln -sf "$LAUNCHER" "$BIN_DIR/agy-model-bridge"

# 5. Check PATH
PATH_NOTICE=""
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        PATH_NOTICE=1
        ;;
esac

echo ""
if [ "$IS_ES" = "1" ]; then
    echo -e "${GREEN}${BOLD}✔ AGY Model Bridge instalado correctamente!${RESET}"
    echo -e "  Binario disponible en: ${BOLD}$LAUNCHER${RESET}"

    if [ -n "$PATH_NOTICE" ]; then
        echo ""
        echo -e "${YELLOW}Nota: ${BIN_DIR} no está actualmente en tu PATH.${RESET}"
        echo -e "Agregalo a tu shell ejecutando:"
        echo -e "  ${BOLD}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc${RESET}"
    fi

    echo ""
    echo -e "${BOLD}Comandos para empezar:${RESET}"
    echo -e "  1. Arrancar el bridge en segundo plano:"
    echo -e "     ${GREEN}agy-bridge start${RESET}"
    echo ""
    echo -e "  2. Configurar tu cliente favorito:"
    echo -e "     ${BLUE}agy-bridge setup-claude${RESET}   # para Claude Code"
    echo -e "     ${BLUE}agy-bridge setup-codex${RESET}    # para Codex CLI"
    echo ""
    echo -e "  3. Ver estado o abrir el dashboard:"
    echo -e "     ${BLUE}agy-bridge status${RESET}"
    echo -e "     ${BLUE}agy-bridge dashboard${RESET}"
    echo ""
    echo -e "  4. Detener el servicio cuando termines:"
    echo -e "     ${YELLOW}agy-bridge stop${RESET}"
    echo ""
else
    echo -e "${GREEN}${BOLD}✔ AGY Model Bridge installed successfully!${RESET}"
    echo -e "  Binary available at: ${BOLD}$LAUNCHER${RESET}"

    if [ -n "$PATH_NOTICE" ]; then
        echo ""
        echo -e "${YELLOW}Note: ${BIN_DIR} is not currently in your PATH.${RESET}"
        echo -e "Add it to your shell by running:"
        echo -e "  ${BOLD}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc${RESET}"
    fi

    echo ""
    echo -e "${BOLD}Commands to get started:${RESET}"
    echo -e "  1. Start the bridge in the background:"
    echo -e "     ${GREEN}agy-bridge start${RESET}"
    echo ""
    echo -e "  2. Configure your favorite client:"
    echo -e "     ${BLUE}agy-bridge setup-claude${RESET}   # for Claude Code"
    echo -e "     ${BLUE}agy-bridge setup-codex${RESET}    # for Codex CLI"
    echo ""
    echo -e "  3. Check status or open the dashboard:"
    echo -e "     ${BLUE}agy-bridge status${RESET}"
    echo -e "     ${BLUE}agy-bridge dashboard${RESET}"
    echo ""
    echo -e "  4. Stop the service when done:"
    echo -e "     ${YELLOW}agy-bridge stop${RESET}"
    echo ""
fi
