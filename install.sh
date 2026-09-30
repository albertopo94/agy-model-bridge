#!/usr/bin/env bash
# AGY Model Bridge - Zero-dependency installer for macOS & Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/albertopo94/agy-model-bridge/main/install.sh | bash

set -e

REPO_URL="https://github.com/albertopo94/agy-model-bridge.git"
INSTALL_DIR="${AGY_BRIDGE_DIR:-$HOME/.agy-bridge/core}"
BIN_DIR="${AGY_BRIDGE_BIN:-$HOME/.local/bin}"

BOLD="\033[1m"
GREEN="\033[32m"
BLUE="\033[34m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

echo -e "${BOLD}${BLUE}==> Instalando AGY Model Bridge...${RESET}"

# 1. Check Python version (>= 3.10 required)
if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}Error: python3 no está instalado. Se requiere Python 3.10 o superior.${RESET}"
    exit 1
fi

PYTHON_OK=$(python3 -c "import sys; print(1 if sys.version_info >= (3, 10) else 0)" 2>/dev/null || echo 0)
if [ "$PYTHON_OK" != "1" ]; then
    PYTHON_VER=$(python3 -V 2>&1)
    echo -e "${RED}Error: $PYTHON_VER no soportado. Se requiere Python 3.10+.${RESET}"
    exit 1
fi

# 2. Check Git
if ! command -v git >/dev/null 2>&1; then
    echo -e "${RED}Error: git no está instalado.${RESET}"
    exit 1
fi

# 3. Clone or update repository
mkdir -p "$(dirname "$INSTALL_DIR")"
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "Actualizando repositorio existente en ${INSTALL_DIR}..."
    git -C "$INSTALL_DIR" pull --quiet || true
else
    echo -e "Descargando en ${INSTALL_DIR}..."
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi

# 4. Create binary launcher wrapper in ~/.local/bin
mkdir -p "$BIN_DIR"
LAUNCHER="$BIN_DIR/agy-bridge"

cat <<'EOF' > "$LAUNCHER"
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_DIR="${AGY_BRIDGE_DIR:-$HOME/.agy-bridge/core}"
export PYTHONPATH="$CORE_DIR:$PYTHONPATH"
exec python3 -u -m bridge "$@"
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
