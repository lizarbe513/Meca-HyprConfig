"""
Módulo IPC para comunicación en tiempo real con Hyprland mediante hyprctl.
"""

from __future__ import annotations
import json
import subprocess
from typing import Any, Dict, List, Optional


class HyprIPC:
    @staticmethod
    def run_hyprctl(args: List[str]) -> Optional[str]:
        """Ejecuta un comando hyprctl y retorna la salida estándar."""
        try:
            res = subprocess.run(
                ["hyprctl"] + args,
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return None

    @classmethod
    def is_running(cls) -> bool:
        """Verifica si Hyprland está activo."""
        return cls.run_hyprctl(["version"]) is not None

    @classmethod
    def get_version_info(cls) -> str:
        """Obtiene la versión corta de Hyprland."""
        out = cls.run_hyprctl(["version"])
        if out:
            for line in out.splitlines():
                if line.startswith("Hyprland"):
                    return line.split(" ")[1]
        return "Desconocido"

    @classmethod
    def get_monitors(cls) -> List[Dict[str, Any]]:
        """Obtiene la lista de monitores activos con sus modos y posiciones."""
        out = cls.run_hyprctl(["monitors", "-j"])
        if out:
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                pass
        return []

    @classmethod
    def get_option(cls, option_name: str) -> Optional[Any]:
        """Obtiene el valor actual de una opción de Hyprland."""
        out = cls.run_hyprctl(["getoption", option_name, "-j"])
        if out:
            try:
                data = json.loads(out)
                for field in ["int", "float", "bool", "str", "css"]:
                    if field in data:
                        return data[field]
                return data
            except json.JSONDecodeError:
                pass
        return None

    @classmethod
    def set_keyword(cls, key: str, value: Any) -> bool:
        """Aplica un cambio de opción en vivo en Hyprland sin recargar sesión."""
        val_str = str(value)
        if isinstance(value, bool):
            val_str = "true" if value else "false"
        out = cls.run_hyprctl(["keyword", key, val_str])
        return out == "ok" or (out is not None and "ok" in out.lower())

    @classmethod
    def reload(cls) -> bool:
        """Recarga la configuración completa de Hyprland."""
        out = cls.run_hyprctl(["reload"])
        return out is not None
