"""
Módulo IPC para comunicación en tiempo real con Hyprland mediante hyprctl.
"""

from __future__ import annotations
import json
import os
import subprocess
import time
from pathlib import Path
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
    def get_active_window(cls) -> Optional[Dict[str, Any]]:
        """Obtiene la información JSON de la ventana actualmente enfocada."""
        out = cls.run_hyprctl(["activewindow", "-j"])
        if out:
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                pass
        return None

    @classmethod
    def get_clients(cls) -> List[Dict[str, Any]]:
        """Obtiene todas las ventanas abiertas en Hyprland."""
        out = cls.run_hyprctl(["clients", "-j"])
        if out:
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                pass
        return []

    @classmethod
    def find_our_window(cls) -> Optional[Dict[str, Any]]:
        """Localiza la ventana de terminal que ejecuta este proceso recorriendo sus PIDs ancestros."""
        ancestor_pids: List[int] = []
        pid = os.getpid()
        for _ in range(12):
            if pid <= 1:
                break
            ancestor_pids.append(pid)
            stat_file = Path(f"/proc/{pid}/stat")
            if not stat_file.exists():
                break
            try:
                content = stat_file.read_text(encoding="utf-8")
                rparen = content.rfind(")")
                if rparen == -1:
                    break
                fields = content[rparen + 2 :].split()
                pid = int(fields[1])  # ppid
            except Exception:
                break

        clients = cls.get_clients()
        pid_to_client = {int(c.get("pid", -1)): c for c in clients if c.get("pid")}
        for anc in ancestor_pids:
            if anc in pid_to_client:
                return pid_to_client[anc]
        return cls.get_active_window()

    @classmethod
    def eval(cls, code: str) -> Optional[str]:
        """Ejecuta código Lua en Hyprland mediante hyprctl eval."""
        return cls.run_hyprctl(["eval", code])

    @classmethod
    def ensure_floating_centered(cls, width: int = 680, height: int = 960) -> bool:
        """
        Convierte la ventana actual en una ventana flotante rectangular vertical (más altura que anchura)
        y centrada. Retorna True si la ventana era originalmente de mosaico (tiled).
        """
        win = None
        for _ in range(6):
            win = cls.find_our_window()
            if win and win.get("address"):
                break
            time.sleep(0.03)

        if not win:
            return False

        monitors = cls.get_monitors()
        if monitors:
            mon = monitors[0]
            scale = float(mon.get("scale", 1.0) or 1.0)
            mon_w = int(mon.get("width", 1920) / scale)
            mon_h = int(mon.get("height", 1080) / scale)
            height = min(height, max(640, mon_h - 60))
            width = min(width, int(mon_w * 0.75))
            # Garantizar que la altura sea siempre notoriamente mayor que la anchura
            if width >= height:
                width = int(height * 0.72)

        addr = str(win.get("address", "")).strip()
        was_tiled = not bool(win.get("floating", False))

        # 1. Intentar mediante parser Lua moderno de Hyprland
        if addr:
            lua_code = f"""
local win = hl.get_window("address:{addr}")
if win then
  hl.dispatch(hl.dsp.window.tag({{ tag = "-floating-window", window = "address:{addr}" }}))
  if not win.floating then
    hl.dispatch(hl.dsp.window.float({{ window = "address:{addr}" }}))
  end
  hl.dispatch(hl.dsp.focus({{ window = "address:{addr}" }}))
  hl.dispatch(hl.dsp.window.resize({{ x = {width}, y = {height}, relative = false, window = "address:{addr}" }}))
  hl.dispatch(hl.dsp.window.center({{ window = "address:{addr}" }}))
else
  local act = hl.get_active_window()
  if act and not act.floating then
    hl.dispatch(hl.dsp.window.float())
  end
  hl.dispatch(hl.dsp.window.resize({{ x = {width}, y = {height}, relative = false }}))
  hl.dispatch(hl.dsp.window.center())
end
"""
        else:
            lua_code = f"""
local win = hl.get_active_window()
if win and not win.floating then
  hl.dispatch(hl.dsp.window.float())
end
hl.dispatch(hl.dsp.window.resize({{ x = {width}, y = {height}, relative = false }}))
hl.dispatch(hl.dsp.window.center())
"""
        res = cls.eval(lua_code)
        if res and "ok" in res.lower():
            return was_tiled

        # 2. Fallback para parser legacy
        cmds: List[str] = []
        if addr:
            cmds.append(f"dispatch tagwindow -floating-window address:{addr}")
            if was_tiled:
                cmds.append(f"dispatch setfloating address:{addr}")
            cmds.append(f"dispatch focuswindow address:{addr}")
            cmds.append(f"dispatch resizewindowpixel exact {width} {height},address:{addr}")
            cmds.append(f"dispatch resizeactive exact {width} {height}")
            cmds.append("dispatch centerwindow")
        else:
            if was_tiled:
                cmds.append("dispatch setfloating")
            cmds.append(f"dispatch resizeactive exact {width} {height}")
            cmds.append("dispatch centerwindow")

        cls.run_hyprctl(["--batch", " ; ".join(cmds)])
        return was_tiled

    @classmethod
    def restore_tiled(cls) -> None:
        """Devuelve la ventana de Meca a modo mosaico (tiled)."""
        win = cls.find_our_window()
        addr = str(win.get("address", "")).strip() if win else ""
        if addr:
            lua_code = f"""
local win = hl.get_window("address:{addr}")
if win and win.floating then
  hl.dispatch(hl.dsp.window.float({{ window = "address:{addr}" }}))
end
"""
            res = cls.eval(lua_code)
            if res and "ok" in res.lower():
                return
            cls.run_hyprctl(["dispatch", "settiled", f"address:{addr}"])
        else:
            lua_code = """
local win = hl.get_active_window()
if win and win.floating then
  hl.dispatch(hl.dsp.window.float())
end
"""
            res = cls.eval(lua_code)
            if res and "ok" in res.lower():
                return
            cls.run_hyprctl(["dispatch", "settiled"])

    @classmethod
    def get_option(cls, option_name: str) -> Optional[Any]:
        """Obtiene el valor actual de una opción de Hyprland."""
        out = cls.run_hyprctl(["getoption", option_name, "-j"])
        if out:
            try:
                data = json.loads(out)
                for field in ["int", "float", "bool", "str", "css", "custom"]:
                    if field in data:
                        return data[field]
                return data
            except json.JSONDecodeError:
                pass
        return None

    @classmethod
    def set_keyword(cls, key: str, value: Any) -> bool:
        """Aplica un cambio de opción en vivo en Hyprland sin recargar sesión."""
        # 1. Intentar mediante parser Lua moderno (Hyprland 0.50+)
        if ":" in key:
            parts = [p.replace("-", "_") for p in key.split(":")]
            if isinstance(value, bool):
                val_lua = "true" if value else "false"
            elif isinstance(value, (int, float)):
                val_lua = str(value)
            else:
                val_lua = json.dumps(str(value))
            expr = val_lua
            for p in reversed(parts):
                expr = f"{{ {p} = {expr} }}"
            res = cls.eval(f"hl.config({expr})")
            if res and "ok" in res.lower():
                return True
        elif key == "monitor":
            m_parts = [p.strip() for p in str(value).split(",")]
            out_name = m_parts[0] if len(m_parts) > 0 else ""
            mode_str = m_parts[1] if len(m_parts) > 1 else "preferred"
            pos_str = m_parts[2] if len(m_parts) > 2 else "auto"
            scale_val = m_parts[3] if len(m_parts) > 3 else "1"
            trans_part = ""
            if "transform" in m_parts:
                t_idx = m_parts.index("transform")
                if t_idx + 1 < len(m_parts):
                    trans_part = f", transform = {m_parts[t_idx+1]}"
            lua_mon = f'hl.monitor({{ output = "{out_name}", mode = "{mode_str}", position = "{pos_str}", scale = {scale_val}{trans_part} }})'
            res = cls.eval(lua_mon)
            if res and "ok" in res.lower():
                return True

        # 2. Fallback para parser legacy
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
