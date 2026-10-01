#!/usr/bin/env bash
# ==============================================================================
# Hook post-update para Meca HyprConfig en Omarchy
# Ejecutado automáticamente tras 'omarchy update'
# ==============================================================================
set -e

# Detectar directorio del repositorio Meca
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"
if [[ ! -d "$SCRIPT_DIR/.git" ]]; then
    if command -v meca &>/dev/null; then
        MECA_BIN="$(command -v meca)"
        while [ -h "$MECA_BIN" ]; do
            DIR="$(cd -P "$(dirname "$MECA_BIN")" >/dev/null 2>&1 && pwd)"
            MECA_BIN="$(readlink "$MECA_BIN")"
            [[ $MECA_BIN != /* ]] && MECA_BIN="$DIR/$MECA_BIN"
        done
        SCRIPT_DIR="$(cd -P "$(dirname "$MECA_BIN")/.." >/dev/null 2>&1 && pwd)"
    elif [[ -d "$HOME/Projects/meca-hyprconfig/.git" ]]; then
        SCRIPT_DIR="$HOME/Projects/meca-hyprconfig"
    fi
fi

if [[ -d "$SCRIPT_DIR/.git" ]] && command -v git &>/dev/null; then
    echo "[MECA] Comprobando actualizaciones del repositorio Meca HyprConfig..."
    git -C "$SCRIPT_DIR" pull --ff-only 2>/dev/null || true
fi

# Re-asegurar tecla Bloq Mayús liberada
if command -v meca &>/dev/null; then
    meca --fix-caps &>/dev/null || true
elif [[ -x "$SCRIPT_DIR/bin/meca" ]]; then
    "$SCRIPT_DIR/bin/meca" --fix-caps &>/dev/null || true
fi

# Re-asegurar entrada en el menú de Omarchy (Setup -> Config)
MENU_EXT="$HOME/.config/omarchy/extensions/omarchy-menu.jsonc"
if [[ -f "$MENU_EXT" ]] && ! grep -q '"setup.config.meca"' "$MENU_EXT"; then
    python3 -c '
import sys
p = sys.argv[1]
try:
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()
    if "setup.config.meca" not in content and "}" in content:
        entry = "\n  \"setup.config.meca\": {\n    \"icon\": \"\ue615\",\n    \"label\": \"Meca\",\n    \"action\": \"omarchy-launch-tui --app-id=org.omarchy.meca meca\"\n  }\n"
        idx = content.rfind("}")
        new_content = content[:idx].rstrip()
        if not new_content.endswith("{") and not new_content.endswith(","):
            new_content += ","
        new_content += entry + "}\n"
        with open(p, "w", encoding="utf-8") as f:
            f.write(new_content)
except Exception:
    pass
' "$MENU_EXT" 2>/dev/null || true
    command -v omarchy &>/dev/null && omarchy menu refresh &>/dev/null || true
fi

exit 0
