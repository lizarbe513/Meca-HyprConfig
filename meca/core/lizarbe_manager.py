"""
Módulo de Gestión de Identidad Lizarbe, Fastfetch y Software Amigable para Omarchy.
"""

from __future__ import annotations
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple


class LizarbeManager:
    @staticmethod
    def is_lizarbe_installed() -> bool:
        """Verifica si el tema Lizarbe está disponible en Omarchy."""
        user_theme = Path.home() / ".config" / "omarchy" / "themes" / "lizarbe"
        sys_theme = Path("/usr/share/omarchy/themes/lizarbe")
        return user_theme.exists() or sys_theme.exists()

    @staticmethod
    def is_fastfetch_lizarbe_configured() -> bool:
        """Verifica si fastfetch tiene configurado el logo personalizado de Lizarbe."""
        cfg_file = Path.home() / ".config" / "fastfetch" / "config.jsonc"
        logo_file = Path.home() / ".config" / "fastfetch" / "logo.txt"
        if cfg_file.exists() and logo_file.exists():
            content = cfg_file.read_text(encoding="utf-8", errors="ignore")
            return "logo.txt" in content
        return False

    @staticmethod
    def ensure_fastfetch_logo() -> bool:
        """Configura el logo de Lizarbe en Fastfetch si no estuviese presente."""
        ff_dir = Path.home() / ".config" / "fastfetch"
        ff_dir.mkdir(parents=True, exist_ok=True)
        logo_file = ff_dir / "logo.txt"
        cfg_file = ff_dir / "config.jsonc"

        if not logo_file.exists():
            # Buscar en el proyecto de temas si está disponible
            alt_logo = Path.home() / "Projects" / "Lizarbe-Omarchy-Theme" / "config" / "fastfetch" / "logo.txt"
            if alt_logo.exists():
                shutil.copy(alt_logo, logo_file)
            else:
                logo_file.write_text(
                    """\033[38;2;227;27;35m
  ███████╗██╗███████╗ █████╗ ██████╗ ██████╗ ███████╗
  ██╔════╝██║╚══███╔╝██╔══██╗██╔══██╗██╔══██╗██╔════╝
  █████╗  ██║  ███╔╝ ███████║██████╔╝██████╔╝█████╗  
  ██╔══╝  ██║ ███╔╝  ██╔══██║██╔══██╗██╔══██╗██╔══╝  
  ██║     ██║███████╗██║  ██║██║  ██║██████╔╝███████╗
  ╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚══════╝
\033[0m""",
                    encoding="utf-8"
                )

        if not cfg_file.exists():
            cfg_file.write_text(
                '{\n  "$schema": "https://github.com/fastfetch-cli/fastfetch/raw/dev/doc/json_schema.json",\n  "logo": {\n    "source": "~/.config/fastfetch/logo.txt"\n  }\n}\n',
                encoding="utf-8"
            )
        else:
            try:
                content = cfg_file.read_text(encoding="utf-8", errors="ignore")
                if "logo.txt" not in content:
                    # Si no tiene logo.txt configurado, enlazarlo en la sección logo
                    if '"logo":' in content:
                        content = re.sub(r'("logo"\s*:\s*\{[^}]*?"source"\s*:\s*)"[^"]*"', r'\1"~/.config/fastfetch/logo.txt"', content)
                    cfg_file.write_text(content, encoding="utf-8")
            except Exception:
                pass

        return True

    @staticmethod
    def check_app_status() -> List[Tuple[str, str, bool]]:
        """Comprueba el estado de programas amigables recomendados."""
        apps = [
            ("Nautilus (Gestor de Archivos)", "nautilus"),
            ("Thunar (Gestor Ligero)", "thunar"),
            ("Pavucontrol (Audio y Micrófono)", "pavucontrol"),
            ("Fastfetch (Información de Sistema)", "fastfetch"),
            ("Brave Browser", "brave"),
            ("Foot Terminal", "foot"),
            ("Ghostty Terminal", "ghostty"),
        ]
        results = []
        for name, cmd in apps:
            installed = shutil.which(cmd) is not None
            results.append((name, cmd, installed))
        return results

    @staticmethod
    def apply_lizarbe_theme(variant: str = "lizarbe") -> bool:
        """Aplica el tema Lizarbe o Lizarbe Light mediante Omarchy."""
        try:
            res = subprocess.run(
                ["omarchy", "theme", "set", variant],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return res.returncode == 0
        except Exception:
            return False
