"""
Motor de Interfaz TUI Monolítica para Meca HyprConfig.
Cero dependencias externas: utiliza modo terminal ANSI nativo con soporte TrueColor
reactivo a los temas de Omarchy.
"""

from __future__ import annotations
import os
import sys
import tty
import termios
import select
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from meca.core.theme_engine import ThemeEngine
from meca.core.hypr_ipc import HyprIPC
from meca.core.config_sync import ConfigSync
from meca.core.lizarbe_manager import LizarbeManager


class MecaTUI:
    TABS = [
        ("1", "🖥️ Pantallas"),
        ("2", "🎨 Apariencia & Temas"),
        ("3", "⚡ Animaciones"),
        ("4", "⌨️ Teclado & Bloq Mayús"),
        ("5", "🖱️ Ratón & Gestos"),
        ("6", "🛡️ Setup Lizarbe"),
    ]

    def __init__(self):
        self.theme_engine = ThemeEngine()
        self.config_sync = ConfigSync()
        self.settings = self.config_sync.load_gui_settings()
        self.monitors = HyprIPC.get_monitors()
        self.available_themes = self.theme_engine.list_available_themes()

        self.current_tab_idx = 1  # 0: Displays, 1: Apariencia, etc.
        self.selected_item_idx = 0
        self.status_message = "Listo. Usa Tab / 1-6 para navegar, Flechas para cambiar valores, Enter o 's' para guardar."
        self.status_time = time.time()
        self.running = True
        self.orig_termios = None

        # Estado específico de pestañas
        self.selected_theme_idx = 0
        if self.theme_engine.current_theme in self.available_themes:
            self.selected_theme_idx = self.available_themes.index(self.theme_engine.current_theme)

        self.selected_monitor_idx = 0
        self.mon_scale_idx = 0  # 1.0, 1.25, 1.5, 2.0
        self.scales = [1.0, 1.25, 1.5, 1.75, 2.0]

    def set_status(self, msg: str) -> None:
        self.status_message = msg
        self.status_time = time.time()

    def run(self) -> None:
        """Inicia el ciclo principal de la interfaz en terminal raw mode."""
        if not sys.stdin.isatty():
            print("Error: meca-hyprconfig debe ejecutarse en una terminal interactiva (TTY).")
            return

        fd = sys.stdin.fileno()
        self.orig_termios = termios.tcgetattr(fd)

        try:
            tty.setraw(fd)
            # Entrar en alternate screen buffer y ocultar cursor
            sys.stdout.write("\033[?1049h\033[?25l")
            sys.stdout.flush()

            while self.running:
                self.render()
                self.handle_input(fd)
        finally:
            # Restaurar cursor, salir de alternate screen y restaurar termios
            sys.stdout.write("\033[?25h\033[?1049l\033[0m")
            sys.stdout.flush()
            if self.orig_termios:
                termios.tcsetattr(fd, termios.TCSADRAIN, self.orig_termios)

    def render(self) -> None:
        """Dibuja la pantalla completa en el buffer del terminal."""
        cols, rows = shutil.get_terminal_size((80, 24))
        buf: List[str] = ["\033[H"]

        accent = "accent"
        bg_col = "background"
        fg_col = "foreground"

        # 1. Barra de Título y Sistema
        ver = HyprIPC.get_version_info()
        title_left = f" MECA HyprConfig — Omarchy Control Center "
        theme_info = f"Tema: {self.theme_engine.current_theme} | Hyprland: {ver} "
        space_len = max(0, cols - len(title_left) - len(theme_info))
        buf.append(self.theme_engine.style("bright_foreground", accent, title_left, bold=True))
        buf.append(self.theme_engine.style("bright_foreground", accent, " " * space_len))
        buf.append(self.theme_engine.style("bright_foreground", accent, theme_info) + "\r\n")

        # 2. Barra de Pestañas
        tab_line = " "
        for i, (num, name) in enumerate(self.TABS):
            if i == self.current_tab_idx:
                tab_line += self.theme_engine.style("bright_foreground", accent, f" [{num}] {name} ", bold=True)
            else:
                tab_line += self.theme_engine.style("foreground", None, f"  [{num}] {name}  ")
            tab_line += " "
        buf.append(tab_line + "\r\n")
        buf.append(self.theme_engine.fg("muted", "─" * cols) + "\r\n")

        # 3. Contenido según pestaña activa
        content_lines = []
        if self.current_tab_idx == 0:
            content_lines = self._render_monitors_tab(cols)
        elif self.current_tab_idx == 1:
            content_lines = self._render_appearance_tab(cols)
        elif self.current_tab_idx == 2:
            content_lines = self._render_animations_tab(cols)
        elif self.current_tab_idx == 3:
            content_lines = self._render_keybinds_tab(cols)
        elif self.current_tab_idx == 4:
            content_lines = self._render_input_tab(cols)
        elif self.current_tab_idx == 5:
            content_lines = self._render_lizarbe_tab(cols)

        # Rellenar filas hasta la barra de estado
        usable_rows = rows - 4
        for r in range(usable_rows):
            if r < len(content_lines):
                line = content_lines[r]
                buf.append(line + "\033[K\r\n")
            else:
                buf.append("\033[K\r\n")

        # 4. Barra de Estado / Atajos inferiores
        status_text = f" {self.status_message}"
        keys_hint = " Tab/1-6: Pestañas | ↑/↓: Elemento | ←/→: Ajustar | Enter/s: Guardar | q: Salir "
        status_space = max(0, cols - len(status_text) - len(keys_hint))
        buf.append(self.theme_engine.style("bright_foreground", "muted", status_text))
        buf.append(self.theme_engine.style("bright_foreground", "muted", " " * status_space))
        buf.append(self.theme_engine.style("bright_foreground", "muted", keys_hint))

        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    # ==========================
    # RENDERIZADO DE PESTAÑAS
    # ==========================

    def _render_monitors_tab(self, cols: int) -> List[str]:
        lines = []
        lines.append(self.theme_engine.style("bright_foreground", None, " 🖥️  CONFIGURACIÓN DE MONITORES Y PANTALLAS", bold=True))
        lines.append(self.theme_engine.fg("muted", " Detecta resolución, frecuencia de refresco (Hz) y escala sin tocar archivos de texto."))
        lines.append("")

        if not self.monitors:
            lines.append("  " + self.theme_engine.fg("yellow", "No se detectaron monitores activos a través de hyprctl."))
            lines.append("  Presiona [r] para reintentar detección.")
            return lines

        # Selector de monitor
        lines.append(self.theme_engine.fg("accent", "  ┌─ Monitores Detectados:"))
        for idx, mon in enumerate(self.monitors):
            prefix = "  │  " + ("► " if idx == self.selected_monitor_idx else "  ")
            mon_desc = f"{mon.get('name', 'Disp')} — {mon.get('description', '')} ({mon.get('width')}x{mon.get('height')} @ {mon.get('refreshRate', 60):.0f}Hz)"
            if idx == self.selected_monitor_idx:
                lines.append(prefix + self.theme_engine.style("bright_foreground", "selection", mon_desc, bold=True))
            else:
                lines.append(prefix + mon_desc)
        lines.append(self.theme_engine.fg("accent", "  └────────────────────────"))
        lines.append("")

        curr_mon = self.monitors[self.selected_monitor_idx]
        lines.append(self.theme_engine.style("bright_foreground", None, f"  Ajustes para {curr_mon.get('name')}:", bold=True))
        
        items = [
            ("Escala de Pantalla (HiDPI)", f"{curr_mon.get('scale', 1.0)}x (Usa ← / → para cambiar)"),
            ("Resolución Actual", f"{curr_mon.get('width')}x{curr_mon.get('height')} @ {curr_mon.get('refreshRate', 60):.1f} Hz"),
            ("Modos Disponibles", f"{len(curr_mon.get('availableModes', []))} resoluciones soportadas"),
            ("Guardar y Aplicar a monitors.lua", "[ Presiona Enter o 's' ]"),
        ]

        for i, (label, val) in enumerate(items):
            is_sel = (i == self.selected_item_idx)
            ptr = "► " if is_sel else "  "
            if is_sel:
                line = f"   {ptr}{self.theme_engine.style('bright_foreground', 'selection', f' {label.ljust(35)} : {val} ')}"
            else:
                line = f"   {ptr}{label.ljust(35)} : {self.theme_engine.fg('accent', val)}"
            lines.append(line)

        return lines

    def _render_appearance_tab(self, cols: int) -> List[str]:
        lines = []
        lines.append(self.theme_engine.style("bright_foreground", None, " 🎨 APARIENCIA, BORDES, GAPS Y TEMAS DE OMARCHY", bold=True))
        lines.append(self.theme_engine.fg("muted", " Personaliza en caliente el aspecto visual de tus ventanas y la paleta del escritorio."))
        lines.append("")

        # Sliders y opciones
        g_out = self.settings.get("gaps_out", 10)
        g_in = self.settings.get("gaps_in", 5)
        rnd = self.settings.get("rounding", 8)
        bs = self.settings.get("border_size", 2)
        dim = "Activado" if self.settings.get("dim_inactive", False) else "Desactivado"
        theme_name = self.available_themes[self.selected_theme_idx] if self.available_themes else "Default"

        items = [
            ("Tema Omarchy", f"<{theme_name}> (Usa ← / → para preseleccionar)", "Cambia colores globales"),
            ("Separación Exterior (gaps_out)", f"{g_out} px  " + self._bar(g_out, 30), "Espacio con la pantalla"),
            ("Separación Entre Ventanas (gaps_in)", f"{g_in} px  " + self._bar(g_in, 20), "Espacio entre apps"),
            ("Esquinas Redondeadas (rounding)", f"{rnd} px  " + self._bar(rnd, 25), "Curvatura de bordes"),
            ("Grosor de Bordes (border_size)", f"{bs} px  " + self._bar(bs, 6), "Línea de contorno"),
            ("Atenuar Ventanas Inactivas (dim)", f"[{dim}]", "Foco visual en ventana activa"),
            ("Aplicar Cambios en Hyprland", "[ Presiona Enter o 's' ]", "Guarda en hyprland-gui.lua"),
        ]

        for i, (label, val, desc) in enumerate(items):
            is_sel = (i == self.selected_item_idx)
            ptr = "► " if is_sel else "  "
            if is_sel:
                line = f"   {ptr}{self.theme_engine.style('bright_foreground', 'selection', f' {label.ljust(35)} : {val.ljust(25)} ')} {self.theme_engine.fg('muted', desc)}"
            else:
                line = f"   {ptr}{label.ljust(35)} : {self.theme_engine.fg('bright_foreground', val.ljust(25))} {self.theme_engine.fg('muted', desc)}"
            lines.append(line)

        lines.append("")
        # Simulación visual de dos ventanas en terminal
        lines.append(self.theme_engine.fg("accent", "   ┌─ Vista Previa Simulada de Ventanas:"))
        lines.append(f"   │  ┌────── Inactiva ──────┐  " + self.theme_engine.style("bright_foreground", "accent", f"┌────── Activa ({rnd}px) ──────┐"))
        lines.append(f"   │  │ $ terminal           │  " + self.theme_engine.style("bright_foreground", "accent", f"│ $ omarchy theme: {theme_name} │"))
        lines.append(f"   │  │   gaps_in: {g_in}px      │  " + self.theme_engine.style("bright_foreground", "accent", f"│   border_size: {bs}px       │"))
        lines.append(f"   │  └──────────────────────┘  " + self.theme_engine.style("bright_foreground", "accent", f"└────────────────────────────┘"))
        lines.append(self.theme_engine.fg("accent", "   └──────────────────────────────────────────────────────────"))

        return lines

    def _render_animations_tab(self, cols: int) -> List[str]:
        lines = []
        lines.append(self.theme_engine.style("bright_foreground", None, " ⚡ ANIMACIONES Y FLUIDEZ DE HYPRLAND", bold=True))
        lines.append(self.theme_engine.fg("muted", " Modifica la velocidad y respuesta en transiciones de ventanas y workspaces."))
        lines.append("")

        anim_on = "Activadas (Fluido)" if self.settings.get("animations_enabled", True) else "Desactivadas (Instantáneo)"
        preset = self.settings.get("animation_preset", "smooth")

        items = [
            ("Animaciones Globales", f"[{anim_on}] (Enter o ← / → para alternar)", "Efectos visuales"),
            ("Preset de Fluidez", f"<{preset.upper()}> (smooth / snappy / minimal)", "Curvas de velocidad"),
            ("Aplicar y Guardar", "[ Presiona Enter o 's' ]", "Actualiza configuración"),
        ]

        for i, (label, val, desc) in enumerate(items):
            is_sel = (i == self.selected_item_idx)
            ptr = "► " if is_sel else "  "
            if is_sel:
                line = f"   {ptr}{self.theme_engine.style('bright_foreground', 'selection', f' {label.ljust(30)} : {val.ljust(30)} ')} {self.theme_engine.fg('muted', desc)}"
            else:
                line = f"   {ptr}{label.ljust(30)} : {self.theme_engine.fg('bright_foreground', val.ljust(30))} {self.theme_engine.fg('muted', desc)}"
            lines.append(line)

        lines.append("")
        lines.append(self.theme_engine.fg("muted", "   Consejo: Desactivar animaciones es ideal en ordenadores de recursos modestos."))
        return lines

    def _render_keybinds_tab(self, cols: int) -> List[str]:
        lines = []
        lines.append(self.theme_engine.style("bright_foreground", None, " ⌨️  TECLADO, ATAJOS Y CORRECCIÓN DE BLOQ MAYÚS", bold=True))
        lines.append(self.theme_engine.fg("muted", " Resuelve la pérdida de la tecla Bloq Mayús y revisa los atajos clave del sistema."))
        lines.append("")

        # Alerta Bloq Mayús
        is_fixed = (self.settings.get("compose_key") == "ralt")
        caps_status = "Corregido: Bloq Mayús NORMAL (Compose en Alt Gr)" if is_fixed else "Default Omarchy (Bloq Mayús = Compose)"

        items = [
            ("Comportamiento Bloq Mayús", f"[{caps_status}]", "Presiona Enter para alternar"),
            ("Aplicar Corrección Ahora", "[ Enter para guardar en input.lua ]", "Libera Bloq Mayús de inmediato"),
        ]

        for i, (label, val, desc) in enumerate(items):
            is_sel = (i == self.selected_item_idx)
            ptr = "► " if is_sel else "  "
            color_val = "green" if is_fixed and i == 0 else "bright_foreground"
            if is_sel:
                line = f"   {ptr}{self.theme_engine.style('bright_foreground', 'selection', f' {label.ljust(30)} : {val.ljust(45)} ')}"
            else:
                line = f"   {ptr}{label.ljust(30)} : {self.theme_engine.fg(color_val, val.ljust(45))}"
            lines.append(line)

        lines.append("")
        lines.append(self.theme_engine.fg("accent", "   ┌─ Atajos Principales de Omarchy + Hyprland (SUPER = Tecla Windows):"))
        binds = [
            ("SUPER + RETURN", "Abrir Terminal principal (foot / ghostty)"),
            ("SUPER + SPACE", "Lanzador de Aplicaciones y Menú Omarchy"),
            ("SUPER + Q", "Cerrar ventana actual"),
            ("SUPER + E", "Explorador de Archivos"),
            ("SUPER + SHIFT + S", "Captura de pantalla recortada"),
            ("SUPER + [1..9]", "Cambiar de Espacio de Trabajo (Workspace)"),
        ]
        for key, desc in binds:
            lines.append(f"   │   {self.theme_engine.style('bright_foreground', 'muted', f' {key.ljust(20)} ')}  → {desc}")
        lines.append(self.theme_engine.fg("accent", "   └───────────────────────────────────────────────────────────────────"))

        return lines

    def _render_input_tab(self, cols: int) -> List[str]:
        lines = []
        lines.append(self.theme_engine.style("bright_foreground", None, " 🖱️  RATÓN, TOUCHPAD Y GESTOS", bold=True))
        lines.append(self.theme_engine.fg("muted", " Sensibilidad de puntero, scroll natural y gestos con dedos."))
        lines.append("")

        sens = self.settings.get("sensitivity", 0.0)
        accel = self.settings.get("accel_profile", "flat")
        nat = "Activado (Inverso smartphone)" if self.settings.get("natural_scroll", False) else "Desactivado (Estándar PC)"

        items = [
            ("Sensibilidad del Ratón", f"{sens:+.2f}  " + self._bar(int((sens + 1.0) * 10), 20), "← / → para calibrar"),
            ("Perfil de Aceleración", f"<{accel.upper()}> (flat: precisa / adaptive: dinámica)", "Enter para alternar"),
            ("Scroll Natural Touchpad", f"[{nat}]", "Enter para alternar"),
            ("Aplicar y Guardar", "[ Presiona Enter o 's' ]", "Guarda en hyprland-gui.lua"),
        ]

        for i, (label, val, desc) in enumerate(items):
            is_sel = (i == self.selected_item_idx)
            ptr = "► " if is_sel else "  "
            if is_sel:
                line = f"   {ptr}{self.theme_engine.style('bright_foreground', 'selection', f' {label.ljust(30)} : {val.ljust(35)} ')} {self.theme_engine.fg('muted', desc)}"
            else:
                line = f"   {ptr}{label.ljust(30)} : {self.theme_engine.fg('bright_foreground', val.ljust(35))} {self.theme_engine.fg('muted', desc)}"
            lines.append(line)

        return lines

    def _render_lizarbe_tab(self, cols: int) -> List[str]:
        lines = []
        lines.append(self.theme_engine.style("bright_foreground", None, " 🛡️  SETUP DE BIENVENIDA & IDENTIDAD LIZARBE", bold=True))
        lines.append(self.theme_engine.fg("muted", " Preparación integral para nuevos usuarios: temas, fastfetch y actualización automática."))
        lines.append("")

        has_lizarbe = LizarbeManager.is_lizarbe_installed()
        has_ff = LizarbeManager.is_fastfetch_lizarbe_configured()
        hook_path = Path.home() / ".config" / "omarchy" / "hooks" / "post-update.d" / "99-meca-hyprconfig.sh"
        has_hook = hook_path.exists()

        items = [
            ("Tema Lizarbe / Lizarbe Light", "[Instalado]" if has_lizarbe else "[No detectado]", "Activar tema completo oficial"),
            ("Logo Lizarbe en Fastfetch", "[Configurado]" if has_ff else "[Sin configurar]", "Banner ASCII en terminal"),
            ("Hook en 'omarchy update'", "[Activo]" if has_hook else "[Inactivo]", "Auto-actualización del panel"),
            ("Aplicar Todo el Setup Lizarbe", "[ Ejecutar Preparación Completa ]", "Configura temas, logo y hook"),
        ]

        for i, (label, val, desc) in enumerate(items):
            is_sel = (i == self.selected_item_idx)
            ptr = "► " if is_sel else "  "
            val_col = "green" if "Instalado" in val or "Configurado" in val or "Activo" in val else "yellow"
            if is_sel:
                line = f"   {ptr}{self.theme_engine.style('bright_foreground', 'selection', f' {label.ljust(32)} : {val.ljust(20)} ')} {self.theme_engine.fg('muted', desc)}"
            else:
                line = f"   {ptr}{label.ljust(32)} : {self.theme_engine.fg(val_col, val.ljust(20))} {self.theme_engine.fg('muted', desc)}"
            lines.append(line)

        lines.append("")
        lines.append(self.theme_engine.fg("accent", "   ┌─ Estado de Software Amigable Recomendado:"))
        for name, cmd, inst in LizarbeManager.check_app_status()[:4]:
            tag = self.theme_engine.fg("green", "✓ Instalado") if inst else self.theme_engine.fg("yellow", "✗ No instalado")
            lines.append(f"   │   {name.ljust(40)} {tag}")
        lines.append(self.theme_engine.fg("accent", "   └────────────────────────────────────────────────────────────"))

        return lines

    def _bar(self, val: int, max_val: int) -> str:
        """Genera una barra de progreso visual en texto."""
        width = 12
        filled = max(0, min(width, int((val / max(1, max_val)) * width)))
        return f"[{'█' * filled}{'░' * (width - filled)}]"

    # ==========================
    # MANEJO DE ENTRADA Y TECLADO
    # ==========================

    def handle_input(self, fd: int) -> None:
        """Lee teclas y eventos de entrada."""
        r, _, _ = select.select([fd], [], [], 0.05)
        if not r:
            return

        ch = os.read(fd, 32)
        if not ch:
            return

        # Tecla Salir
        if ch in (b"q", b"Q", b"\x1b") and len(ch) == 1:
            self.running = False
            return

        # Números 1 a 6 para cambiar de pestaña directamente
        if ch in [b"1", b"2", b"3", b"4", b"5", b"6"]:
            self.current_tab_idx = int(ch.decode()) - 1
            self.selected_item_idx = 0
            return

        # Tab o Shift+Tab
        if ch == b"\t":
            self.current_tab_idx = (self.current_tab_idx + 1) % len(self.TABS)
            self.selected_item_idx = 0
            return
        if ch == b"\x1b[Z":  # Shift+Tab
            self.current_tab_idx = (self.current_tab_idx - 1) % len(self.TABS)
            self.selected_item_idx = 0
            return

        # Guardar rápido con 's' o 'S'
        if ch in (b"s", b"S"):
            self.save_all()
            return

        # Flecha Arriba
        if ch == b"\x1b[A":
            self.selected_item_idx = max(0, self.selected_item_idx - 1)
            return

        # Flecha Abajo
        if ch == b"\x1b[B":
            max_items = self._get_max_items_for_tab()
            self.selected_item_idx = min(max_items - 1, self.selected_item_idx + 1)
            return

        # Flecha Izquierda / Derecha / Enter
        if ch == b"\x1b[D":  # Left
            self._on_adjust(delta=-1)
            return
        if ch == b"\x1b[C":  # Right
            self._on_adjust(delta=1)
            return

        if ch in (b"\r", b"\n"):  # Enter
            self._on_activate()
            return

    def _get_max_items_for_tab(self) -> int:
        counts = [4, 7, 3, 2, 4, 4]
        return counts[self.current_tab_idx]

    def _on_adjust(self, delta: int) -> None:
        """Ajusta valores con las flechas izquierda y derecha."""
        tab = self.current_tab_idx
        idx = self.selected_item_idx

        # Pestaña 0: Monitores
        if tab == 0:
            if idx == 0 and self.monitors:  # Escala
                self.mon_scale_idx = (self.mon_scale_idx + delta) % len(self.scales)
                new_scale = self.scales[self.mon_scale_idx]
                self.monitors[self.selected_monitor_idx]["scale"] = new_scale
                self.set_status(f"Escala cambiada a {new_scale}x (Presiona Enter para aplicar en monitors.lua).")

        # Pestaña 1: Apariencia
        elif tab == 1:
            if idx == 0:  # Tema
                if self.available_themes:
                    self.selected_theme_idx = (self.selected_theme_idx + delta) % len(self.available_themes)
                    t_name = self.available_themes[self.selected_theme_idx]
                    self.set_status(f"Tema preseleccionado: {t_name}. Presiona Enter para aplicar al sistema.")
            elif idx == 1:  # gaps_out
                val = max(0, min(50, self.settings.get("gaps_out", 10) + delta))
                self.settings["gaps_out"] = val
                HyprIPC.set_keyword("general:gaps_out", val)
            elif idx == 2:  # gaps_in
                val = max(0, min(30, self.settings.get("gaps_in", 5) + delta))
                self.settings["gaps_in"] = val
                HyprIPC.set_keyword("general:gaps_in", val)
            elif idx == 3:  # rounding
                val = max(0, min(30, self.settings.get("rounding", 8) + delta))
                self.settings["rounding"] = val
                HyprIPC.set_keyword("decoration:rounding", val)
            elif idx == 4:  # border_size
                val = max(0, min(10, self.settings.get("border_size", 2) + delta))
                self.settings["border_size"] = val
                HyprIPC.set_keyword("general:border_size", val)
            elif idx == 5:  # dim_inactive
                val = not self.settings.get("dim_inactive", False)
                self.settings["dim_inactive"] = val
                HyprIPC.set_keyword("decoration:dim_inactive", val)

        # Pestaña 2: Animaciones
        elif tab == 2:
            if idx == 0:
                val = not self.settings.get("animations_enabled", True)
                self.settings["animations_enabled"] = val
                HyprIPC.set_keyword("animations:enabled", val)
            elif idx == 1:
                presets = ["smooth", "snappy", "minimal"]
                cur = self.settings.get("animation_preset", "smooth")
                next_idx = (presets.index(cur) + delta) % len(presets) if cur in presets else 0
                self.settings["animation_preset"] = presets[next_idx]

        # Pestaña 4: Input / Ratón
        elif tab == 4:
            if idx == 0:  # Sensibilidad
                val = round(max(-1.0, min(1.0, self.settings.get("sensitivity", 0.0) + delta * 0.1)), 2)
                self.settings["sensitivity"] = val
                HyprIPC.set_keyword("input:sensitivity", val)
            elif idx == 1:  # accel_profile
                acc = "adaptive" if self.settings.get("accel_profile") == "flat" else "flat"
                self.settings["accel_profile"] = acc
            elif idx == 2:  # natural_scroll
                val = not self.settings.get("natural_scroll", False)
                self.settings["natural_scroll"] = val
                HyprIPC.set_keyword("input:touchpad:natural_scroll", val)

    def _on_activate(self) -> None:
        """Acción al presionar Enter sobre el elemento seleccionado."""
        tab = self.current_tab_idx
        idx = self.selected_item_idx

        # Pestaña 0: Monitores
        if tab == 0:
            if self.monitors:
                cur = self.monitors[self.selected_monitor_idx]
                res = f"{cur.get('width')}x{cur.get('height')}"
                hz = float(cur.get('refreshRate', 60.0))
                scale = float(cur.get('scale', 1.0))
                ok = self.config_sync.save_monitor_config(cur.get('name'), res, hz, scale)
                self.set_status(f"✓ Configuración de monitor {cur.get('name')} guardada y aplicada." if ok else "Error al guardar monitor.")

        # Pestaña 1: Apariencia
        elif tab == 1:
            if idx == 0:  # Aplicar tema
                t_name = self.available_themes[self.selected_theme_idx]
                self.set_status(f"Aplicando tema {t_name} mediante Omarchy...")
                self.render()
                if self.theme_engine.set_theme(t_name):
                    self.set_status(f"✓ Tema {t_name} activado con éxito.")
                else:
                    self.set_status(f"Error al cambiar tema a {t_name}.")
            elif idx == 5:  # Toggle Dim
                self._on_adjust(1)
            elif idx == 6:  # Guardar
                self.save_all()

        # Pestaña 2: Animaciones
        elif tab == 2:
            if idx in (0, 1):
                self._on_adjust(1)
            elif idx == 2:
                self.save_all()

        # Pestaña 3: Teclado & Bloq Mayús
        elif tab == 3:
            if idx == 0:  # Toggle opción
                cur = self.settings.get("compose_key", "ralt")
                self.settings["compose_key"] = "caps" if cur == "ralt" else "ralt"
            elif idx in (0, 1):
                use_ralt = (self.settings.get("compose_key") == "ralt")
                self.config_sync.fix_caps_lock(use_ralt=use_ralt)
                msg = "✓ Bloq Mayús LIBERADO (Tecla Compose ahora es Alt Gr)." if use_ralt else "Restaurado Bloq Mayús como Compose."
                self.set_status(msg)

        # Pestaña 4: Input / Ratón
        elif tab == 4:
            if idx in (1, 2):
                self._on_adjust(1)
            elif idx == 3:
                self.save_all()

        # Pestaña 5: Setup Lizarbe
        elif tab == 5:
            if idx == 0:  # Activar Lizarbe
                self.set_status("Aplicando tema oficial Lizarbe...")
                self.render()
                if LizarbeManager.apply_lizarbe_theme("lizarbe"):
                    self.theme_engine.reload()
                    self.set_status("✓ Tema Lizarbe aplicado correctamente.")
                else:
                    self.set_status("Error al aplicar tema Lizarbe.")
            elif idx == 1:  # Fastfetch
                LizarbeManager.ensure_fastfetch_logo()
                self.set_status("✓ Logo de Lizarbe asegurado en ~/.config/fastfetch/logo.txt.")
            elif idx == 2:  # Instalar hook
                self.install_update_hook()
            elif idx == 3:  # Todo junto
                self.set_status("Configurando Setup Lizarbe Completo...")
                self.render()
                LizarbeManager.apply_lizarbe_theme("lizarbe")
                LizarbeManager.ensure_fastfetch_logo()
                self.config_sync.fix_caps_lock(use_ralt=True)
                self.install_update_hook()
                self.save_all()
                self.theme_engine.reload()
                self.set_status("✓ ¡Setup Lizarbe completado! Tema, Fastfetch, Bloq Mayús y Hook configurados.")

    def save_all(self) -> None:
        """Guarda toda la configuración en hyprland-gui.lua y aplica en vivo."""
        ok = self.config_sync.save_gui_settings(self.settings, apply_live=True)
        if ok:
            self.set_status("✓ Ajustes guardados en ~/.config/hypr/hyprland-gui.lua y aplicados en vivo.")
        else:
            self.set_status("Error al guardar ajustes en hyprland-gui.lua.")

    def install_update_hook(self) -> None:
        """Instala el hook post-update en ~/.config/omarchy/hooks/post-update.d/."""
        hook_dir = Path.home() / ".config" / "omarchy" / "hooks" / "post-update.d"
        hook_dir.mkdir(parents=True, exist_ok=True)
        hook_file = hook_dir / "99-meca-hyprconfig.sh"
        
        script_dir = Path(__file__).resolve().parent.parent.parent
        hook_content = f"""#!/usr/bin/env bash
# ==============================================================================
# Hook post-update para Meca HyprConfig en Omarchy
# Ejecutado automáticamente por 'omarchy update'
# ==============================================================================
set -e

REPO_DIR="{script_dir}"
if [[ -d "$REPO_DIR/.git" ]] && command -v git &>/dev/null; then
    echo "[MECA] Actualizando repositorio Meca HyprConfig..."
    git -C "$REPO_DIR" pull --ff-only 2>/dev/null || true
fi

# Re-asegurar tecla Bloq Mayús
if command -v meca &>/dev/null; then
    meca --fix-caps &>/dev/null || true
fi

exit 0
"""
        try:
            hook_file.write_text(hook_content, encoding="utf-8")
            hook_file.chmod(0o755)
            self.set_status("✓ Hook instalado en ~/.config/omarchy/hooks/post-update.d/99-meca-hyprconfig.sh.")
        except Exception:
            self.set_status("Error al crear el hook de actualización.")
