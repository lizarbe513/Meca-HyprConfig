#!/usr/bin/env bash
# ==============================================================================
# Hook post-update para Meca HyprConfig en Omarchy
# Ejecutado automáticamente tras 'omarchy update'
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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

exit 0
