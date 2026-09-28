"""
Módulo de Integración con Temas de Omarchy.
Detecta el tema activo, lee colors.toml y genera secuencias ANSI de color.
"""

from __future__ import annotations
import os
import subprocess
import tomllib
from pathlib import Path
from typing import Dict, Any, List, Optional


class ThemeEngine:
    def __init__(self):
        self.user_themes_dir = Path.home() / ".config" / "omarchy" / "themes"
        self.system_themes_dir = Path("/usr/share/omarchy/themes")
        self._current_theme_name: Optional[str] = None
        self._colors: Dict[str, str] = {}
        self.reload()

    def get_current_theme_name(self) -> str:
        """Obtiene el nombre del tema activo a través de omarchy."""
        try:
            res = subprocess.run(
                ["omarchy", "theme", "current"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass

        # Fallback comprobando ~/.config/omarchy/current/theme o Rose Pine
        current_link = Path.home() / ".config" / "omarchy" / "current" / "theme"
        if current_link.exists() and current_link.is_symlink():
            target = os.readlink(current_link)
            return Path(target).name

        return "Rose Pine"

    def list_available_themes(self) -> List[str]:
        """Lista todos los temas disponibles en el sistema y usuario."""
        themes = set()
        for d in [self.user_themes_dir, self.system_themes_dir]:
            if d.exists() and d.is_dir():
                for item in d.iterdir():
                    if item.is_dir() and (item / "colors.toml").exists():
                        themes.add(item.name)
        return sorted(list(themes))

    def _find_theme_dir(self, theme_name: str) -> Optional[Path]:
        """Localiza el directorio del tema, priorizando la ruta de usuario."""
        # 1. Nombre exacto
        candidates = [
            self.user_themes_dir / theme_name,
            self.system_themes_dir / theme_name,
            self.user_themes_dir / theme_name.lower().replace(" ", "-"),
            self.system_themes_dir / theme_name.lower().replace(" ", "-"),
            self.user_themes_dir / theme_name.lower().replace(" ", ""),
            self.system_themes_dir / theme_name.lower().replace(" ", ""),
        ]
        for c in candidates:
            if c.exists() and (c / "colors.toml").exists():
                return c

        # 2. Búsqueda insensible a mayúsculas
        lower_name = theme_name.lower().replace(" ", "").replace("-", "")
        for base in [self.user_themes_dir, self.system_themes_dir]:
            if base.exists():
                for item in base.iterdir():
                    if item.is_dir():
                        cleaned = item.name.lower().replace(" ", "").replace("-", "")
                        if cleaned == lower_name and (item / "colors.toml").exists():
                            return item
        return None

    def reload(self) -> None:
        """Recarga la configuración del tema actual."""
        self._current_theme_name = self.get_current_theme_name()
        theme_dir = self._find_theme_dir(self._current_theme_name)
        
        default_colors = {
            "accent": "#E31B23",
            "selection": "#E31B23",
            "background": "#08080B",
            "foreground": "#d8d8d8",
            "muted": "#444444",
            "red": "#E31B23",
            "green": "#2DB872",
            "yellow": "#E5A83B",
            "blue": "#5A7DA8",
            "cyan": "#45A0B5",
            "bright_foreground": "#ffffff",
        }

        if theme_dir:
            colors_file = theme_dir / "colors.toml"
            if colors_file.exists():
                try:
                    with open(colors_file, "rb") as f:
                        data = tomllib.load(f)
                        for k, v in data.items():
                            if isinstance(v, str) and v.startswith("#"):
                                default_colors[k] = v
                except Exception:
                    pass

        self._colors = default_colors

    @property
    def current_theme(self) -> str:
        return self._current_theme_name or "Desconocido"

    @property
    def colors(self) -> Dict[str, str]:
        return self._colors

    @staticmethod
    def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
        hex_clean = hex_str.lstrip("#")
        if len(hex_clean) == 3:
            hex_clean = "".join(c * 2 for c in hex_clean)
        if len(hex_clean) >= 6:
            return (
                int(hex_clean[0:2], 16),
                int(hex_clean[2:4], 16),
                int(hex_clean[4:6], 16),
            )
        return (255, 255, 255)

    def fg(self, color_key: str, text: str) -> str:
        """Devuelve el texto coloreado con truecolor ANSI (primer plano)."""
        hex_val = self._colors.get(color_key, "#ffffff")
        r, g, b = self.hex_to_rgb(hex_val)
        return f"\033[38;2;{r};{g};{b}m{text}\033[0m"

    def bg(self, color_key: str, text: str) -> str:
        """Devuelve el texto coloreado con truecolor ANSI (fondo)."""
        hex_val = self._colors.get(color_key, "#000000")
        r, g, b = self.hex_to_rgb(hex_val)
        return f"\033[48;2;{r};{g};{b}m{text}\033[0m"

    def style(self, fg_key: str, bg_key: Optional[str], text: str, bold: bool = False) -> str:
        """Aplica estilos combinados de primer plano, fondo y negrita."""
        prefix = "\033[1m" if bold else ""
        fg_hex = self._colors.get(fg_key, "#ffffff")
        fr, fg_val, fb = self.hex_to_rgb(fg_hex)
        prefix += f"\033[38;2;{fr};{fg_val};{fb}m"

        if bg_key:
            bg_hex = self._colors.get(bg_key, "#000000")
            br, bg_val, bb = self.hex_to_rgb(bg_hex)
            prefix += f"\033[48;2;{br};{bg_val};{bb}m"

        return f"{prefix}{text}\033[0m"

    def set_theme(self, theme_name: str) -> bool:
        """Aplica un tema utilizando omarchy theme set."""
        try:
            res = subprocess.run(
                ["omarchy", "theme", "set", theme_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0:
                self.reload()
                return True
        except Exception:
            pass
        return False
