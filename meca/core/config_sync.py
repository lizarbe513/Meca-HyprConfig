"""
Módulo de Sincronización y Persistencia de Configuraciones en Archivos Lua de Hyprland.
Garantiza persistencia completa en hyprland-gui.lua, autostart.lua, input.lua y monitors.lua.
"""

from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, List
from meca.core.hypr_ipc import HyprIPC


class ConfigSync:
    def __init__(self):
        self.hypr_dir = Path.home() / ".config" / "hypr"
        self.gui_file = self.hypr_dir / "hyprland-gui.lua"
        self.input_file = self.hypr_dir / "input.lua"
        self.monitors_file = self.hypr_dir / "monitors.lua"
        self.autostart_file = self.hypr_dir / "autostart.lua"
        self.ensure_paths()

    def ensure_paths(self) -> None:
        """Crea el directorio de configuración si no existe."""
        self.hypr_dir.mkdir(parents=True, exist_ok=True)

    def load_gui_settings(self) -> Dict[str, Any]:
        """Carga los ajustes actuales desde hyprctl y desde hyprland-gui.lua."""
        settings: Dict[str, Any] = {
            "gaps_in": 5,
            "gaps_out": 10,
            "border_size": 2,
            "resize_on_border": True,
            "layout": "dwindle",
            "allow_tearing": False,
            "snap_enabled": False,
            "rounding": 0,
            "active_opacity": 1.0,
            "inactive_opacity": 0.95,
            "dim_inactive": False,
            "dim_strength": 0.15,
            "blur_enabled": True,
            "blur_size": 5,
            "blur_passes": 2,
            "shadow_enabled": True,
            "animations_enabled": True,
            "animation_preset": "smooth",
            "anim_windows": "popin 80%",
            "anim_workspaces": "slide",
            "no_hw_cursors": False,
            "cursor_timeout": 0,
            "cursor_zoom": 1.0,
            "repeat_rate": 40,
            "repeat_delay": 250,
            "numlock": True,
            "sensitivity": 0.0,
            "accel_profile": "flat",
            "natural_scroll": False,
            "clickfinger": True,
            "tap_to_click": True,
            "disable_typing": True,
            "workspace_swipe": True,
            "workspace_count": 5,
            "workspace_layout": "dwindle",
            "dwindle_force_split": 2,
            "dwindle_preserve_split": True,
            "dwindle_smart_split": False,
            "master_new_status": "slave",
            "rules_pavucontrol_float": True,
            "rules_calculator_float": True,
            "compose_key": "ralt",
        }

        # Consultar opciones en vivo de Hyprland
        live_int_map = {
            "general:border_size": "border_size",
            "decoration:rounding": "rounding",
            "decoration:blur:size": "blur_size",
            "decoration:blur:passes": "blur_passes",
            "cursor:inactive_timeout": "cursor_timeout",
            "input:repeat_rate": "repeat_rate",
            "input:repeat_delay": "repeat_delay",
            "dwindle:force_split": "dwindle_force_split",
        }
        for hypr_k, s_k in live_int_map.items():
            val = HyprIPC.get_option(hypr_k)
            if isinstance(val, int):
                settings[s_k] = int(val)

        live_bool_map = {
            "general:resize_on_border": "resize_on_border",
            "general:allow_tearing": "allow_tearing",
            "general:snap:enabled": "snap_enabled",
            "decoration:dim_inactive": "dim_inactive",
            "decoration:blur:enabled": "blur_enabled",
            "decoration:shadow:enabled": "shadow_enabled",
            "animations:enabled": "animations_enabled",
            "cursor:no_hardware_cursors": "no_hw_cursors",
            "input:numlock_by_default": "numlock",
            "input:touchpad:natural_scroll": "natural_scroll",
            "input:touchpad:clickfinger_behavior": "clickfinger",
            "input:touchpad:tap-to-click": "tap_to_click",
            "input:touchpad:disable_while_typing": "disable_typing",
            "dwindle:preserve_split": "dwindle_preserve_split",
            "dwindle:smart_split": "dwindle_smart_split",
        }
        for hypr_k, s_k in live_bool_map.items():
            val = HyprIPC.get_option(hypr_k)
            if val is not None and isinstance(val, (bool, int)):
                settings[s_k] = bool(val)

        live_float_map = {
            "decoration:active_opacity": "active_opacity",
            "decoration:inactive_opacity": "inactive_opacity",
            "decoration:dim_strength": "dim_strength",
            "cursor:zoom_factor": "cursor_zoom",
            "input:sensitivity": "sensitivity",
        }
        for hypr_k, s_k in live_float_map.items():
            val = HyprIPC.get_option(hypr_k)
            if val is not None:
                try:
                    settings[s_k] = round(float(val), 2)
                except (ValueError, TypeError):
                    pass

        live_str_map = {
            "general:layout": "layout",
            "input:accel_profile": "accel_profile",
            "master:new_status": "master_new_status",
        }
        for hypr_k, s_k in live_str_map.items():
            val = HyprIPC.get_option(hypr_k)
            if isinstance(val, str) and val.strip():
                settings[s_k] = val.strip()

        # Parsear gaps (pueden venir como "5 5 5 5" en custom)
        for hypr_k, s_k in [("general:gaps_in", "gaps_in"), ("general:gaps_out", "gaps_out")]:
            g_val = HyprIPC.get_option(hypr_k)
            if isinstance(g_val, int):
                settings[s_k] = g_val
            elif isinstance(g_val, str):
                first = g_val.split()[0] if g_val.split() else ""
                if first.isdigit():
                    settings[s_k] = int(first)

        # Verificar compose_key en input.lua o hyprctl
        kb_opts = HyprIPC.get_option("input:kb_options")
        if isinstance(kb_opts, str):
            if "compose:caps" in kb_opts:
                settings["compose_key"] = "caps"
            elif "compose:ralt" in kb_opts:
                settings["compose_key"] = "ralt"

        return settings

    @staticmethod
    def _b(val: Any) -> str:
        return "true" if bool(val) else "false"

    def save_gui_settings(self, settings: Dict[str, Any], apply_live: bool = True) -> bool:
        """Escribe todos los ajustes en ~/.config/hypr/hyprland-gui.lua y los aplica en vivo."""
        b = self._b
        pavu_rule = (
            '\nif o and o.window then\n  o.window("(org.pulseaudio.pavucontrol|pavucontrol)", { float = true, center = true, size = { 760, 520 } })\nend\n'
            if settings.get("rules_pavucontrol_float", True)
            else ""
        )
        calc_rule = (
            'if o and o.window then\n  o.window("(org.gnome.Calculator|qalculate-gtk|omacalc)", { float = true, center = true })\nend\n'
            if settings.get("rules_calculator_float", True)
            else ""
        )

        lua_content = f"""-- Generado automáticamente por Meca HyprConfig (MECA)
-- No modificar manualmente este bloque si utilizas el panel TUI.

hl.config({{
  general = {{
    gaps_in = {int(settings.get('gaps_in', 5))},
    gaps_out = {int(settings.get('gaps_out', 10))},
    border_size = {int(settings.get('border_size', 2))},
    resize_on_border = {b(settings.get('resize_on_border', True))},
    allow_tearing = {b(settings.get('allow_tearing', False))},
    layout = "{settings.get('layout', 'dwindle')}",
    snap = {{
      enabled = {b(settings.get('snap_enabled', False))},
    }},
  }},
  decoration = {{
    rounding = {int(settings.get('rounding', 0))},
    active_opacity = {float(settings.get('active_opacity', 1.0)):.2f},
    inactive_opacity = {float(settings.get('inactive_opacity', 0.95)):.2f},
    dim_inactive = {b(settings.get('dim_inactive', False))},
    dim_strength = {float(settings.get('dim_strength', 0.15)):.2f},
    blur = {{
      enabled = {b(settings.get('blur_enabled', True))},
      size = {int(settings.get('blur_size', 5))},
      passes = {int(settings.get('blur_passes', 2))},
    }},
    shadow = {{
      enabled = {b(settings.get('shadow_enabled', True))},
    }},
  }},
  animations = {{
    enabled = {b(settings.get('animations_enabled', True))},
  }},
  cursor = {{
    no_hardware_cursors = {b(settings.get('no_hw_cursors', False))},
    inactive_timeout = {int(settings.get('cursor_timeout', 0))},
    zoom_factor = {float(settings.get('cursor_zoom', 1.0)):.2f},
  }},
  input = {{
    repeat_rate = {int(settings.get('repeat_rate', 40))},
    repeat_delay = {int(settings.get('repeat_delay', 250))},
    numlock_by_default = {b(settings.get('numlock', True))},
    sensitivity = {float(settings.get('sensitivity', 0.0)):.2f},
    accel_profile = "{settings.get('accel_profile', 'flat')}",
    touchpad = {{
      natural_scroll = {b(settings.get('natural_scroll', False))},
      clickfinger_behavior = {b(settings.get('clickfinger', True))},
      tap_to_click = {b(settings.get('tap_to_click', True))},
      disable_while_typing = {b(settings.get('disable_typing', True))},
    }},
  }},
  dwindle = {{
    force_split = {int(settings.get('dwindle_force_split', 2))},
    preserve_split = {b(settings.get('dwindle_preserve_split', True))},
    smart_split = {b(settings.get('dwindle_smart_split', False))},
  }},
  master = {{
    new_status = "{settings.get('master_new_status', 'slave')}",
  }},
}})

-- Regla de ventana flotante rectangular vertical y centrada para Meca HyprConfig
if o and o.window then
  o.window("(org.omarchy.meca|meca-hyprconfig|TUI.float)", {{ float = true, center = true, size = {{ 760, 920 }} }})
end
{pavu_rule}{calc_rule}"""
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

            # Aplicar en vivo mediante hyprctl
            if apply_live:
                live_pairs = [
                    ("general:gaps_in", settings.get("gaps_in", 5)),
                    ("general:gaps_out", settings.get("gaps_out", 10)),
                    ("general:border_size", settings.get("border_size", 2)),
                    ("general:resize_on_border", settings.get("resize_on_border", True)),
                    ("general:allow_tearing", settings.get("allow_tearing", False)),
                    ("general:layout", settings.get("layout", "dwindle")),
                    ("general:snap:enabled", settings.get("snap_enabled", False)),
                    ("decoration:rounding", settings.get("rounding", 0)),
                    ("decoration:active_opacity", settings.get("active_opacity", 1.0)),
                    ("decoration:inactive_opacity", settings.get("inactive_opacity", 0.95)),
                    ("decoration:dim_inactive", settings.get("dim_inactive", False)),
                    ("decoration:dim_strength", settings.get("dim_strength", 0.15)),
                    ("decoration:blur:enabled", settings.get("blur_enabled", True)),
                    ("decoration:blur:size", settings.get("blur_size", 5)),
                    ("decoration:blur:passes", settings.get("blur_passes", 2)),
                    ("decoration:shadow:enabled", settings.get("shadow_enabled", True)),
                    ("animations:enabled", settings.get("animations_enabled", True)),
                    ("cursor:no_hardware_cursors", settings.get("no_hw_cursors", False)),
                    ("cursor:inactive_timeout", settings.get("cursor_timeout", 0)),
                    ("cursor:zoom_factor", settings.get("cursor_zoom", 1.0)),
                    ("input:repeat_rate", settings.get("repeat_rate", 40)),
                    ("input:repeat_delay", settings.get("repeat_delay", 250)),
                    ("input:numlock_by_default", settings.get("numlock", True)),
                    ("input:sensitivity", settings.get("sensitivity", 0.0)),
                    ("input:accel_profile", settings.get("accel_profile", "flat")),
                    ("input:touchpad:natural_scroll", settings.get("natural_scroll", False)),
                    ("input:touchpad:clickfinger_behavior", settings.get("clickfinger", True)),
                    ("input:touchpad:tap_to_click", settings.get("tap_to_click", True)),
                    ("input:touchpad:disable_while_typing", settings.get("disable_typing", True)),
                    ("dwindle:force_split", settings.get("dwindle_force_split", 2)),
                    ("dwindle:preserve_split", settings.get("dwindle_preserve_split", True)),
                    ("dwindle:smart_split", settings.get("dwindle_smart_split", False)),
                    ("master:new_status", settings.get("master_new_status", "slave")),
                ]
                for k, v in live_pairs:
                    HyprIPC.set_keyword(k, v)

            return True
        except Exception:
            return False

    # =========================================================================
    # GESTIÓN DE AUTOSTART (~/.config/hypr/autostart.lua)
    # =========================================================================

    def list_installed_applications(self) -> List[Dict[str, str]]:
        """
        Escanea archivos .desktop del sistema y del usuario para ofrecer un buscador
        y selector de aplicaciones y servicios en la sección Autostart.
        Retorna una lista ordenada de diccionarios: [{"name": "...", "cmd": "...", "kind": "launch"|"exec"}]
        """
        desktop_dirs = [
            Path("/usr/share/applications"),
            Path("/usr/local/share/applications"),
            Path.home() / ".local" / "share" / "applications",
            Path("/var/lib/flatpak/exports/share/applications"),
            Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
        ]
        apps: List[Dict[str, str]] = []
        seen_cmds = set()

        # Servicios de fondo frecuentes en Hyprland / Omarchy
        builtin_services = [
            ("Hyprsunset (Filtro de luz nocturna)", "hyprsunset", "launch"),
            ("NetworkManager Applet (Bandeja de red)", "nm-applet --indicator", "launch"),
            ("Blueman Applet (Bandeja Bluetooth)", "blueman-applet", "launch"),
            ("Cliphist (Historial de portapapeles)", "wl-paste --watch cliphist store", "exec"),
            ("Waybar (Barra de estado)", "waybar", "launch"),
            ("Mako (Servidor de notificaciones)", "mako", "launch"),
        ]
        for b_name, b_cmd, b_kind in builtin_services:
            seen_cmds.add(b_cmd)
            apps.append({"name": b_name, "cmd": b_cmd, "kind": b_kind})

        for d in desktop_dirs:
            if not d.exists() or not d.is_dir():
                continue
            for p in sorted(d.glob("*.desktop")):
                try:
                    raw_txt = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                # Tomar únicamente la sección principal [Desktop Entry]
                entry_section = raw_txt.split("\n[Desktop Action")[0]
                if (
                    re.search(r"^NoDisplay\s*=\s*true", entry_section, re.M | re.I)
                    or re.search(r"^Hidden\s*=\s*true", entry_section, re.M | re.I)
                ):
                    continue

                m_name = re.search(r"^Name\s*=\s*(.+)$", entry_section, re.M)
                m_exec = re.search(r"^Exec\s*=\s*(.+)$", entry_section, re.M)
                if not (m_name and m_exec):
                    continue

                name = m_name.group(1).strip()
                exec_raw = m_exec.group(1).strip()
                # Limpiar placeholders de especificación Desktop Entry (%U, %F, %f, %u, etc.)
                exec_clean = re.sub(r"\s+%[fFuUdDnNickvm]", "", exec_raw).strip()
                exec_clean = re.sub(r'^"([^"]+)"$', r"\1", exec_clean).strip()
                # Si es ruta simple en /usr/bin/<bin>, simplificar al nombre del binario para mayor legibilidad
                if exec_clean.startswith("/usr/bin/") and " " not in exec_clean:
                    exec_clean = exec_clean[len("/usr/bin/"):]

                if not exec_clean or exec_clean in seen_cmds or exec_clean == "meca":
                    continue
                seen_cmds.add(exec_clean)
                apps.append({
                    "name": name,
                    "cmd": exec_clean,
                    "kind": "launch",
                })

        apps.sort(key=lambda x: x["name"].lower())
        return apps

    def load_autostart_items(self) -> List[Dict[str, Any]]:
        """
        Lee ~/.config/hypr/autostart.lua y devuelve una lista de entradas:
        [{"cmd": "...", "kind": "launch" | "exec", "enabled": bool}]
        """
        items: List[Dict[str, Any]] = []
        seen_cmds = set()

        if self.autostart_file.exists():
            try:
                lines = self.autostart_file.read_text(encoding="utf-8").splitlines()
                pat = re.compile(
                    r"^\s*(--\s*)?o\.(launch_on_start|exec_on_start)\(\s*[\"'](.+?)[\"']\s*\)"
                )
                for line in lines:
                    m = pat.match(line)
                    if m:
                        is_commented = bool(m.group(1))
                        fn_name = m.group(2)
                        cmd = m.group(3).strip()
                        # Ignorar el ejemplo genérico de plantilla "my-service"
                        if cmd == "my-service":
                            continue
                        if cmd not in seen_cmds:
                            seen_cmds.add(cmd)
                            items.append({
                                "cmd": cmd,
                                "kind": "launch" if fn_name == "launch_on_start" else "exec",
                                "enabled": not is_commented,
                            })
            except Exception:
                pass

        # Asegurar que algunas utilidades comunes aparezcan en la lista para fácil activación
        default_suggestions = [
            ("hyprsunset", "launch", False),
            ("nm-applet --indicator", "launch", False),
            ("blueman-applet", "launch", False),
        ]
        for s_cmd, s_kind, s_en in default_suggestions:
            if s_cmd not in seen_cmds:
                seen_cmds.add(s_cmd)
                items.append({
                    "cmd": s_cmd,
                    "kind": s_kind,
                    "enabled": s_en,
                })

        return items

    def save_autostart_items(self, items: List[Dict[str, Any]]) -> bool:
        """Escribe la lista de entradas de autostart en ~/.config/hypr/autostart.lua."""
        out_lines = [
            "-- Procesos, servicios y comandos de inicio gestionados por Meca HyprConfig.",
            "-- Usa o.launch_on_start(\"app\") para aplicaciones/servicios y o.exec_on_start(\"cmd\") para comandos.",
            "",
        ]
        for entry in items:
            cmd = str(entry.get("cmd", "")).strip().replace('"', '\\"')
            if not cmd:
                continue
            kind = entry.get("kind", "launch")
            enabled = bool(entry.get("enabled", True))
            fn = "o.launch_on_start" if kind == "launch" else "o.exec_on_start"
            prefix = "" if enabled else "-- "
            out_lines.append(f'{prefix}{fn}("{cmd}")')

        out_lines.append("")
        try:
            self.autostart_file.write_text("\n".join(out_lines), encoding="utf-8")
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
        HyprIPC.set_keyword("input:kb_options", compose_opt)

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
                encoding="utf-8",
            )
        return True

    def save_monitor_config(self, monitor_name: str, resolution: str, hz: float, scale: float, x: int = 0, y: int = 0) -> bool:
        """Guarda y aplica la configuración de un monitor en monitors.lua usando la sintaxis nativa de Omarchy."""
        gdk_scale = 2 if scale >= 1.5 else 1
        out_name = monitor_name or ""
        mode_str = f"{resolution}@{hz:.2f}" if resolution else "preferred"
        lua_content = f"""-- See https://wiki.hypr.land/Configuring/Basics/Monitors/
-- Gestionado por Meca HyprConfig

local omarchy_gdk_scale = {gdk_scale}
local omarchy_monitor_scale = {scale}

hl.env("GDK_SCALE", tostring(omarchy_gdk_scale))
hl.monitor({{ output = "{out_name}", mode = "{mode_str}", position = "{x}x{y}", scale = omarchy_monitor_scale }})
"""
        try:
            with open(self.monitors_file, "w", encoding="utf-8") as f:
                f.write(lua_content)

            HyprIPC.set_keyword("monitor", f"{out_name},{mode_str},{x}x{y},{scale}")
            return True
        except Exception:
            return False
