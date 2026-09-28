"""
Módulo de Sincronización y Persistencia de Configuraciones en Archivos Lua de Hyprland.
Garantiza persistencia sin romper actualizaciones del sistema Omarchy.
"""

from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional
from meca.core.hypr_ipc import HyprIPC


class ConfigSync:
    def __init__(self):
        self.hypr_dir = Path.home() / ".config" / "hypr"
        self.gui_file = self.hypr_dir / "hyprland-gui.lua"
        self.input_file = self.hypr_dir / "input.lua"
        self.monitors_file = self.hypr_dir / "monitors.lua"
        self.ensure_paths()

    def ensure_paths(self) -> None:
        """Crea el directorio de configuración si no existe."""
        self.hypr_dir.mkdir(parents=True, exist_ok=True)

    def load_gui_settings(self) -> Dict[str, Any]:
        """Carga los ajustes actuales desde hyprctl y del archivo hyprland-gui.lua."""
        settings = {
            "gaps_in": 5,
            "gaps_out": 10,
            "border_size": 2,
            "rounding": 8,
            "dim_inactive": False,
            "animations_enabled": True,
            "animation_preset": "smooth",
            "sensitivity": 0.0,
            "accel_profile": "flat",
            "natural_scroll": False,
            "layout": "dwindle",
            "compose_key": "ralt",  # ralt = Alt Gr (libera Bloq Mayús)
        }

        # Extraer valores reales de Hyprland si está activo
        val = HyprIPC.get_option("general:border_size")
        if val is not None:
            settings["border_size"] = int(val)

        val = HyprIPC.get_option("decoration:rounding")
        if val is not None:
            settings["rounding"] = int(val)

        val = HyprIPC.get_option("decoration:dim_inactive")
        if val is not None:
            settings["dim_inactive"] = bool(val)

        val = HyprIPC.get_option("animations:enabled")
        if val is not None:
            settings["animations_enabled"] = bool(val)

        val = HyprIPC.get_option("input:sensitivity")
        if val is not None:
            try:
                settings["sensitivity"] = float(val)
            except ValueError:
                pass

        val = HyprIPC.get_option("input:touchpad:natural_scroll")
        if val is not None:
            settings["natural_scroll"] = bool(val)

        # Parsear gaps si es posible
        g_in = HyprIPC.get_option("general:gaps_in")
        if g_in and isinstance(g_in, str):
            first = g_in.split()[0]
            if first.isdigit():
                settings["gaps_in"] = int(first)

        g_out = HyprIPC.get_option("general:gaps_out")
        if g_out and isinstance(g_out, str):
            first = g_out.split()[0]
            if first.isdigit():
                settings["gaps_out"] = int(first)

        return settings

    def save_gui_settings(self, settings: Dict[str, Any], apply_live: bool = True) -> bool:
        """Escribe los ajustes en ~/.config/hypr/hyprland-gui.lua y los aplica en vivo."""
        dim_str = "true" if settings.get("dim_inactive", False) else "false"
        anim_str = "true" if settings.get("animations_enabled", True) else "false"
        nat_str = "true" if settings.get("natural_scroll", False) else "false"
        
        lua_content = f"""-- Generado automáticamente por Meca HyprConfig (MECA)
-- No modificar manualmente este bloque si utilizas el panel TUI.

hl.config({{
  general = {{
    gaps_in = {settings.get('gaps_in', 5)},
    gaps_out = {settings.get('gaps_out', 10)},
    border_size = {settings.get('border_size', 2)},
    layout = "{settings.get('layout', 'dwindle')}",
  }},
  decoration = {{
    rounding = {settings.get('rounding', 8)},
    dim_inactive = {dim_str},
    dim_strength = 0.15,
  }},
  animations = {{
    enabled = {anim_str},
  }},
  input = {{
    sensitivity = {settings.get('sensitivity', 0.0):.2f},
    accel_profile = "{settings.get('accel_profile', 'flat')}",
    touchpad = {{
      natural_scroll = {nat_str},
    }},
  }},
}})
"""
        try:
            with open(self.gui_file, "w", encoding="utf-8") as f:
                f.write(lua_content)

            # Comprobar si hyprland.lua tiene require("hyprland-gui")
            hyprland_lua = self.hypr_dir / "hyprland.lua"
            if hyprland_lua.exists():
                text = hyprland_lua.read_text(encoding="utf-8")
                if 'require("hyprland-gui")' not in text:
                    with open(hyprland_lua, "a", encoding="utf-8") as f:
                        f.write('\n-- HyprMod & Meca managed settings\nrequire("hyprland-gui")\n')

            # Aplicar en vivo
            if apply_live:
                HyprIPC.set_keyword("general:gaps_in", settings.get("gaps_in", 5))
                HyprIPC.set_keyword("general:gaps_out", settings.get("gaps_out", 10))
                HyprIPC.set_keyword("general:border_size", settings.get("border_size", 2))
                HyprIPC.set_keyword("decoration:rounding", settings.get("rounding", 8))
                HyprIPC.set_keyword("decoration:dim_inactive", settings.get("dim_inactive", False))
                HyprIPC.set_keyword("animations:enabled", settings.get("animations_enabled", True))
                HyprIPC.set_keyword("input:sensitivity", settings.get("sensitivity", 0.0))
                HyprIPC.set_keyword("input:touchpad:natural_scroll", settings.get("natural_scroll", False))

            return True
        except Exception:
            return False

    def fix_caps_lock(self, use_ralt: bool = True) -> bool:
        """
        Corrige la tecla Bloq Mayús en Hyprland.
        En Omarchy, kb_options por defecto incluye compose:caps.
        Cambiándolo a compose:ralt (Alt Gr), Bloq Mayús recupera su uso normal.
        """
        compose_opt = "compose:ralt" if use_ralt else "compose:caps"
        
        # 1. Aplicar en vivo
        HyprIPC.set_keyword("input:kb_options", compose_opt)

        # 2. Persistir en input.lua si existe o crearlo
        if self.input_file.exists():
            content = self.input_file.read_text(encoding="utf-8")
            if "compose:caps" in content or "compose:ralt" in content:
                content = content.replace("compose:caps", compose_opt).replace("compose:ralt", compose_opt)
            else:
                content += f'\n-- Meca: Corrección de tecla Bloq Mayús\nhl.config({{\n  input = {{\n    kb_options = "{compose_opt}",\n  }},\n}})\n'
            self.input_file.write_text(content, encoding="utf-8")
        else:
            self.input_file.write_text(
                f'-- Configuración de entrada gestionada por Meca\nhl.config({{\n  input = {{\n    kb_options = "{compose_opt}",\n  }},\n}})\n',
                encoding="utf-8"
            )
        return True

    def save_monitor_config(self, monitor_name: str, resolution: str, hz: float, scale: float, x: int = 0, y: int = 0) -> bool:
        """Guarda y aplica la configuración de un monitor en monitors.lua y hyprctl."""
        line = f"monitor = {monitor_name}, {resolution}@{hz:.2f}, {x}x{y}, {scale}\n"
        lua_content = f"""-- Generado por Meca HyprConfig
hl.config({{
  monitor = {{
    "{monitor_name}, {resolution}@{hz:.2f}, {x}x{y}, {scale}",
  }},
}})
"""
        try:
            with open(self.monitors_file, "w", encoding="utf-8") as f:
                f.write(lua_content)
            
            # Aplicar en vivo
            HyprIPC.set_keyword("monitor", f"{monitor_name},{resolution}@{hz:.2f},{x}x{y},{scale}")
            return True
        except Exception:
            return False
