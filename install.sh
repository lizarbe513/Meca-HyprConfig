#!/usr/bin/env bash
# ==============================================================================
# Script de Instalación para Meca HyprConfig (MECA) en Omarchy
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "\033[1;38;2;227;27;35m"
echo "  ███╗   ███╗███████╗ ██████╗ █████╗ "
echo "  ████╗ ████║██╔════╝██╔════╝██╔══██╗"
echo "  ██╔████╔██║█████╗  ██║     ███████║"
echo "  ██║╚██╔╝██║██╔══╝  ██║     ██╔══██║"
echo "  ██║ ╚═╝ ██║███████╗╚██████╗██║  ██║"
echo "  ╚═╝     ╚═╝╚══════╝ ╚═════╝╚═╝  ╚═╝"
echo "  HyprConfig for Omarchy & Hyprland"
echo -e "\033[0m"

echo "[1/5] Instalando ejecutables en ~/.local/bin/ ..."
mkdir -p "$HOME/.local/bin"
ln -sfn "$SCRIPT_DIR/bin/meca-hyprconfig" "$HOME/.local/bin/meca-hyprconfig"
ln -sfn "$SCRIPT_DIR/bin/meca" "$HOME/.local/bin/meca"

# Intentar instalar en /usr/local/bin si se ejecuta con permisos
if [[ -w "/usr/local/bin" ]]; then
    ln -sfn "$SCRIPT_DIR/bin/meca-hyprconfig" "/usr/local/bin/meca-hyprconfig"
    ln -sfn "$SCRIPT_DIR/bin/meca" "/usr/local/bin/meca"
    echo "  -> Enlazado también en /usr/local/bin/meca"
fi

echo "[2/5] Registrando entrada de escritorio (.desktop) ..."
mkdir -p "$HOME/.local/share/applications"
cp -f "$SCRIPT_DIR/meca.desktop" "$HOME/.local/share/applications/meca.desktop"

echo "[3/5] Instalando hook de actualización automática con 'omarchy update' ..."
HOOK_DIR="$HOME/.config/omarchy/hooks/post-update.d"
mkdir -p "$HOOK_DIR"
cp -f "$SCRIPT_DIR/hooks/99-meca-hyprconfig.sh" "$HOOK_DIR/99-meca-hyprconfig.sh"
chmod +x "$HOOK_DIR/99-meca-hyprconfig.sh"

echo "[4/5] Configurando enlace con Hyprland (~/.config/hypr/hyprland-gui.lua) ..."
mkdir -p "$HOME/.config/hypr"
HYPR_LUA="$HOME/.config/hypr/hyprland.lua"
if [[ -f "$HYPR_LUA" ]] && ! grep -q 'require("hyprland-gui")' "$HYPR_LUA"; then
    echo -e '\n-- HyprMod & Meca managed settings\nrequire("hyprland-gui")' >> "$HYPR_LUA"
fi

echo "[5/5] Aplicando corrección de tecla Bloq Mayús y preparación Lizarbe ..."
"$SCRIPT_DIR/bin/meca" --fix-caps
"$SCRIPT_DIR/bin/meca" --status

echo ""
echo -e "\033[32m✔ ¡Meca HyprConfig se ha instalado correctamente!\033[0m"
echo -e "Puedes abrirlo en cualquier momento ejecutando: \033[1;33mmeca\033[0m"
echo "O buscándolo como 'Meca HyprConfig' en el lanzador de aplicaciones (SUPER + SPACE)."
