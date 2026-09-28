"""
Motor TUI Monolítico Minimalista para Meca HyprConfig.
Estructura estilo HyprMod (sidebar categorizada) con diseño sobrio y cuadrado
inspirado en los widgets nativos de Omarchy.
"""

from __future__ import annotations
import os
import sys
import re
import tty
import termios
import select
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from meca.core.theme_engine import ThemeEngine
from meca.core.hypr_ipc import HyprIPC
from meca.core.config_sync import ConfigSync
from meca.core.lizarbe_manager import LizarbeManager


class SectionItem:
    def __init__(
        self,
        key: str,
        name: str,
        desc: str,
        item_type: str,  # 'stepper', 'toggle', 'select', 'slider', 'action'
        min_val: float = 0,
        max_val: float = 100,
        step: float = 1,
        options: Optional[List[str]] = None,
        category: str = "LOOK & FEEL",
    ):
        self.key = key
        self.name = name
        self.desc = desc
        self.item_type = item_type
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.options = options or []
        self.category = category


class MecaTUI:
    # Categorías y Secciones estilo HyprMod / GNOME
    SECTIONS = [
        # LOOK & FEEL
        ("LOOK & FEEL", "general", "", "General", "Gaps, bordes, layout y snap"),
        ("LOOK & FEEL", "decoration", "", "Decoration", "Rounding, blur, opacidad y sombras"),
        ("LOOK & FEEL", "animations", "", "Animations", "Velocidad y transiciones de ventanas"),
        ("LOOK & FEEL", "cursor", "󰍽", "Cursor", "Hardware cursor y comportamiento"),

        # INPUT
        ("INPUT", "keybinds", "", "Keybinds", "Atajos y corrección de Bloq Mayús"),
        ("INPUT", "devices", "󰍽", "Devices", "Sensibilidad, aceleración y touchpad"),

        # DISPLAY
        ("DISPLAY", "monitors", "󰍹", "Monitors", "Resolución, Hz y escala HiDPI"),
        ("DISPLAY", "workspaces", "󰕰", "Workspaces", "Espacios de trabajo y reglas"),

        # WINDOW MANAGEMENT
        ("WINDOW MANAGEMENT", "layouts", "󰕮", "Layouts", "Dwindle y Master tiling options"),
        ("WINDOW MANAGEMENT", "rules", "", "Window Rules", "Reglas flotantes y transparencias"),

        # STARTUP & EXTRAS
        ("STARTUP & EXTRAS", "autostart", "", "Autostart", "Programas de inicio automático"),
        ("STARTUP & EXTRAS", "omarchy", "󰚰", "Omarchy & Lizarbe", "Temas, Fastfetch y actualización"),
    ]

    def __init__(self):
        self.theme_engine = ThemeEngine()
        self.config_sync = ConfigSync()
        self.settings = self.config_sync.load_gui_settings()
        self.monitors = HyprIPC.get_monitors()
        self.available_themes = self.theme_engine.list_available_themes()

        self.current_section_idx = 0
        self.active_pane = "sidebar"  # 'sidebar' o 'content'
        self.selected_item_idx = 0
        self.content_scroll_offset = 0

        self.status_message = "Listo. [Tab] cambiar foco | [↑/↓] navegar | [←/→] ajustar | [s] guardar | [q] salir"
        self.running = True
        self.orig_termios = None

        # Escalas soportadas para monitores
        self.scales = ["1x", "1.25x", "1.5x", "1.75x", "2x"]
        self.scale_values = [1.0, 1.25, 1.5, 1.75, 2.0]

        # Mapeos de coordenadas para interacción con el ratón
        self._sidebar_click_map: Dict[int, int] = {}
        self._content_click_map: Dict[int, Dict[str, Any]] = {}

        # Inicializar definiciones de variables por sección
        self.section_items = self._init_section_items()

    def _init_section_items(self) -> Dict[str, List[SectionItem]]:
        themes = self.available_themes if self.available_themes else ["Rose Pine", "Lizarbe"]

        return {
            "general": [
                SectionItem("general:gaps_in", "Inner gaps", "Separación entre ventanas en píxeles (gaps_in)", "stepper", 0, 30, 1),
                SectionItem("general:gaps_out", "Outer gaps", "Separación respecto a los bordes de la pantalla (gaps_out)", "stepper", 0, 50, 1),
                SectionItem("general:border_size", "Border size", "Grosor de la línea del borde de ventanas en píxeles", "stepper", 0, 10, 1),
                SectionItem("general:resize_on_border", "Resize on border", "Permite redimensionar haciendo clic y arrastre en bordes", "toggle"),
                SectionItem("general:layout", "Layout", "Gestor de mosaico principal (dwindle / master / scrolling)", "select", options=["dwindle", "master", "scrolling"]),
                SectionItem("general:allow_tearing", "Allow tearing", "Permite screen tearing para menor latencia en juegos", "toggle"),
                SectionItem("general:snap:enabled", "Enable snap", "Ajuste magnético automático para ventanas flotantes", "toggle"),
            ],
            "decoration": [
                SectionItem("decoration:rounding", "Rounding", "Radio de esquinas redondeadas en píxeles (0 = recto)", "stepper", 0, 30, 1),
                SectionItem("decoration:active_opacity", "Active opacity", "Opacidad de la ventana activa (1.0 = opaco)", "slider", 0.1, 1.0, 0.05),
                SectionItem("decoration:inactive_opacity", "Inactive opacity", "Opacidad de ventanas no enfocadas (1.0 = opaco)", "slider", 0.1, 1.0, 0.05),
                SectionItem("decoration:dim_inactive", "Dim inactive", "Atenúa la iluminación de ventanas inactivas", "toggle"),
                SectionItem("decoration:dim_strength", "Dim strength", "Intensidad del efecto de atenuación en ventanas inactivas", "slider", 0.0, 1.0, 0.05),
                SectionItem("decoration:blur:enabled", "Blur enabled", "Desenfoque de fondo tipo Kawase para transparencias", "toggle"),
                SectionItem("decoration:blur:size", "Blur size", "Radio del algoritmo de desenfoque", "stepper", 1, 15, 1),
                SectionItem("decoration:blur:passes", "Blur passes", "Número de pasadas de filtrado (mayor = más suave)", "stepper", 1, 6, 1),
                SectionItem("decoration:shadow:enabled", "Drop shadows", "Habilita sombras exteriores bajo las ventanas", "toggle"),
            ],
            "animations": [
                SectionItem("animations:enabled", "Enable animations", "Habilita transiciones y animaciones de Hyprland", "toggle"),
                SectionItem("animations:preset", "Animation preset", "Preset de velocidad de curvas bezier", "select", options=["smooth", "snappy", "minimal"]),
                SectionItem("animations:windows", "Windows animation", "Animación al abrir, cerrar o mover ventanas", "select", options=["popin 80%", "slide", "fade"]),
                SectionItem("animations:workspaces", "Workspaces animation", "Animación de transición al cambiar de escritorio", "select", options=["slide", "slidefade", "fade"]),
            ],
            "cursor": [
                SectionItem("cursor:no_hardware_cursors", "Disable HW cursor", "Desactiva cursor por hardware (corrige parpadeos Nvidia)", "toggle"),
                SectionItem("cursor:inactive_timeout", "Inactive timeout", "Segundos de inactividad antes de ocultar el puntero (0 = nunca)", "stepper", 0, 30, 1),
                SectionItem("cursor:zoom_factor", "Zoom factor", "Factor de aumento de pantalla con cursor", "slider", 1.0, 3.0, 0.25),
            ],
            "keybinds": [
                SectionItem("input:compose_key", "Tecla Bloq Mayús", "Alt Gr = Compose (Bloq Mayús normal) vs Omarchy default", "select", options=["Alt Gr (Compose) [Normal]", "Bloq Mayús (Compose)"]),
                SectionItem("action:fix_caps", "Aplicar corrección Bloq Mayús", "Guarda la opción en input.lua y libera Bloq Mayús", "action"),
                SectionItem("input:repeat_rate", "Keyboard repeat rate", "Frecuencia de repetición de teclas en Hz", "stepper", 10, 80, 5),
                SectionItem("input:repeat_delay", "Keyboard repeat delay", "Retardo antes de iniciar repetición continua (ms)", "stepper", 150, 600, 25),
                SectionItem("input:numlock_by_default", "Numlock by default", "Activa el teclado numérico al iniciar sesión", "toggle"),
            ],
            "devices": [
                SectionItem("input:sensitivity", "Mouse sensitivity", "Sensibilidad del puntero (-1.0 a 1.0)", "slider", -1.0, 1.0, 0.1),
                SectionItem("input:accel_profile", "Acceleration profile", "Perfil de aceleración (flat = precisa, adaptive = dinámica)", "select", options=["flat", "adaptive"]),
                SectionItem("input:touchpad:natural_scroll", "Natural scroll", "Dirección inversa de scroll (estilo smartphone)", "toggle"),
                SectionItem("input:touchpad:clickfinger_behavior", "Clickfinger behavior", "Clic con dos dedos equivale a clic secundario", "toggle"),
                SectionItem("input:touchpad:tap-to-click", "Tap to click", "Tocar el touchpad genera un clic primario", "toggle"),
                SectionItem("input:touchpad:disable_while_typing", "Disable while typing", "Inhabilita el touchpad temporalmente al escribir", "toggle"),
                SectionItem("gestures:workspace_swipe", "Workspace swipe", "Gesto de 3 dedos en touchpad para cambiar escritorios", "toggle"),
            ],
            "monitors": [
                SectionItem("display:scale", "Monitor scale", "Escala de visualización HiDPI para la pantalla activa", "select", options=self.scales),
                SectionItem("display:mode", "Display resolution & Hz", "Modo y frecuencia de actualización del monitor", "select", options=["1920x1080@60Hz", "1920x1080@75Hz", "1280x720@60Hz"]),
                SectionItem("action:save_monitor", "Guardar configuración de monitor", "Escribe los cambios en ~/.config/hypr/monitors.lua", "action"),
            ],
            "workspaces": [
                SectionItem("workspace:count", "Persistent workspaces", "Cantidad de escritorios fijos en la barra", "stepper", 1, 10, 1),
                SectionItem("workspace:layout_toggle", "Workspace layout", "Alternar entre modo dwindle o modo niri (scrolling)", "select", options=["dwindle", "scrolling"]),
            ],
            "layouts": [
                SectionItem("dwindle:pseudotile", "Dwindle pseudotile", "Permite que ventanas de mosaico mantengan tamaño original", "toggle"),
                SectionItem("dwindle:preserve_split", "Preserve split", "Mantiene la dirección de división al cerrar ventanas", "toggle"),
                SectionItem("dwindle:smart_split", "Smart split", "Determina división según posición del cursor", "toggle"),
                SectionItem("master:new_status", "Master new status", "Ubicación de ventanas recién creadas (master / slave)", "select", options=["master", "slave"]),
            ],
            "rules": [
                SectionItem("rules:pavucontrol_float", "Float Pavucontrol", "Abre el panel de audio Pavucontrol como ventana flotante", "toggle"),
                SectionItem("rules:calculator_float", "Float Calculator", "Abre la calculadora en modo flotante centrado", "toggle"),
            ],
            "autostart": [
                SectionItem("autostart:waybar", "Omarchy Shell / Bar", "Inicia la barra superior automáticamente", "toggle"),
                SectionItem("autostart:swaync", "Notification center", "Demonio de notificaciones de escritorio", "toggle"),
                SectionItem("autostart:fastfetch", "Fastfetch on terminal", "Muestra información de sistema al abrir terminal", "toggle"),
            ],
            "omarchy": [
                SectionItem("omarchy:theme", "Active Omarchy Theme", "Aplica el tema visual completo al sistema", "select", options=themes),
                SectionItem("omarchy:icons", "Icon Theme", "Tema de iconos en el sistema", "select", options=["Lizarbe-Red", "Papirus-Dark", "Adwaita"]),
                SectionItem("action:apply_lizarbe_full", "Aplicar Setup Lizarbe Oficial", "Configura Tema Lizarbe, iconos Red y logo Fastfetch", "action"),
                SectionItem("action:install_hook", "Registrar hook en 'omarchy update'", "Mantiene Meca actualizado automáticamente", "action"),
            ],
        }

    def run(self) -> None:
        """Ciclo principal TUI en modo crudo."""
        if not sys.stdin.isatty():
            print("Error: meca debe ejecutarse en una terminal TTY.")
            return

        fd = sys.stdin.fileno()
        self.orig_termios = termios.tcgetattr(fd)

        try:
            tty.setraw(fd)
            # Alternate screen buffer, ocultar cursor y habilitar ratón SGR (1000, 1002, 1006)
            sys.stdout.write("\033[?1049h\033[?25l\033[?1000h\033[?1002h\033[?1006h")
            sys.stdout.flush()

            while self.running:
                self.render()
                self.handle_input(fd)
        finally:
            # Deshabilitar ratón, mostrar cursor y salir de alternate buffer
            sys.stdout.write("\033[?1006l\033[?1002l\033[?1000l\033[?25h\033[?1049l\033[0m")
            sys.stdout.flush()
            if self.orig_termios:
                termios.tcsetattr(fd, termios.TCSADRAIN, self.orig_termios)

    # ==========================
    # RENDERIZADO
    # ==========================

    def render(self) -> None:
        cols, rows = shutil.get_terminal_size((90, 26))
        sidebar_w = 26
        content_w = cols - sidebar_w - 1  # 1 para el separador vertical
        buf: List[str] = ["\033[H"]

        # 1. Barra de Título Superior (Estilo Terminal Sobrio)
        ver = HyprIPC.get_version_info()
        title_left = f" MECA HyprConfig "
        title_right = f"Hyprland {ver} | Tema: {self.theme_engine.current_theme} "
        space_len = max(0, cols - len(title_left) - len(title_right))
        buf.append(self.theme_engine.style("bright_foreground", "accent", title_left, bold=True))
        buf.append(self.theme_engine.style("bright_foreground", "accent", " " * space_len))
        buf.append(self.theme_engine.style("bright_foreground", "accent", title_right) + "\r\n")

        # 2. Render de Cuerpo Dividido (Sidebar + Content)
        body_rows = rows - 3  # Menos header y footer
        sidebar_lines = self._render_sidebar(sidebar_w, body_rows)
        content_lines = self._render_content(content_w, body_rows)

        sep_char = "│"
        for r in range(body_rows):
            s_line = sidebar_lines[r] if r < len(sidebar_lines) else " " * sidebar_w
            c_line = content_lines[r] if r < len(content_lines) else ""
            buf.append(s_line + self.theme_engine.fg("muted", sep_char) + c_line + "\033[K\r\n")

        # 3. Barra Inferior de Estado (Sobria, Cuadrada)
        status_txt = f" {self.status_message}"
        keys_hint = " [Tab]: Cambiar foco | [↑/↓]: Mover | [←/→]: Ajustar | [s]: Guardar | [q]: Salir "
        footer_space = max(0, cols - len(status_txt) - len(keys_hint))
        buf.append(self.theme_engine.style("bright_foreground", "muted", status_txt))
        buf.append(self.theme_engine.style("bright_foreground", "muted", " " * footer_space))
        buf.append(self.theme_engine.style("bright_foreground", "muted", keys_hint))

        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    def _render_sidebar(self, width: int, max_rows: int) -> List[str]:
        lines: List[str] = []
        current_cat = None
        self._sidebar_click_map.clear()

        for idx, (cat, sec_id, icon, title, desc) in enumerate(self.SECTIONS):
            # Encabezado de Categoría en mayúsculas
            if cat != current_cat:
                current_cat = cat
                lines.append(self.theme_engine.style("muted", None, f" {cat}".ljust(width)[:width], bold=True))

            is_sel = (idx == self.current_section_idx)
            is_active_pane = (self.active_pane == "sidebar")

            # Mapear fila de pantalla (1-indexed: row 1 es header, luego líneas de sidebar)
            screen_row = 2 + len(lines)
            self._sidebar_click_map[screen_row] = idx

            # Iconos SOLO en el sidebar izquierdo, sin emojis
            item_text = f" {icon} {title}".ljust(width)
            if len(item_text) > width:
                item_text = item_text[:width]

            if is_sel and is_active_pane:
                # Cuadro de selección sobrio y rectangular (Estilo Omarchy / macOS)
                line = self.theme_engine.style("bright_foreground", "selection", item_text, bold=True)
            elif is_sel:
                line = self.theme_engine.style("bright_foreground", "muted", item_text, bold=True)
            else:
                line = self.theme_engine.style("foreground", None, item_text)

            lines.append(line)

        # Rellenar filas sobrantes
        while len(lines) < max_rows:
            lines.append(" " * width)

        return lines[:max_rows]

    def _render_content(self, width: int, max_rows: int) -> List[str]:
        lines: List[str] = []
        sec_meta = self.SECTIONS[self.current_section_idx]
        sec_id = sec_meta[1]
        sec_title = sec_meta[3]
        sec_desc = sec_meta[4]
        self._content_click_map.clear()

        # Encabezado de la Sección Activa
        lines.append(" " + self.theme_engine.style("bright_foreground", None, sec_title.upper(), bold=True))
        lines.append(" " + self.theme_engine.fg("muted", sec_desc))
        lines.append(" " + self.theme_engine.fg("muted", "─" * (width - 2)))

        items = self.section_items.get(sec_id, [])
        is_active_pane = (self.active_pane == "content")
        sidebar_w = 26

        for i, item in enumerate(items):
            is_sel = (i == self.selected_item_idx and is_active_pane)
            val_str = self._format_item_control(item, width)

            # Nombre y descripción
            title_part = f"  {item.name}"
            space_middle = max(2, width - len(title_part) - len(val_str) - 3)

            # Calcular coordenadas absolutas de la fila y el control
            item_screen_row = 2 + len(lines)
            control_x_start = 1 + sidebar_w + 1 + 1 + len(title_part) + space_middle
            control_x_end = control_x_start + len(val_str)

            click_info = {
                "item_idx": i,
                "item": item,
                "control_range": (control_x_start, control_x_end),
                "minus_range": (control_x_start, control_x_start + 5),
                "plus_range": (control_x_end - 5, control_x_end),
                "slider_range": (control_x_start, control_x_start + 11),
            }
            self._content_click_map[item_screen_row] = click_info
            self._content_click_map[item_screen_row + 1] = click_info  # clic en descripción también selecciona

            if is_sel:
                # Fila seleccionada con caja rectangular sobria (Estilo Omarchy Widget)
                row_str = f" {title_part}{' ' * space_middle}{val_str} "
                lines.append(self.theme_engine.style("bright_foreground", "selection", row_str, bold=True))
                desc_str = f"   └─ {item.desc}"
                lines.append(self.theme_engine.fg("muted", desc_str[:width]))
            else:
                row_str = f" {title_part}{' ' * space_middle}{val_str} "
                lines.append(row_str)
                desc_str = f"   {item.desc}"
                lines.append(self.theme_engine.fg("muted", desc_str[:width]))

            lines.append("")  # Espacio entre items

        while len(lines) < max_rows:
            lines.append(" " * width)

        return lines[:max_rows]

    def _format_item_control(self, item: SectionItem, max_w: int) -> str:
        """Formatea el control interactivo: Stepper, Toggle, Select o Slider."""
        val = self._get_item_value(item)

        if item.item_type == "stepper":
            # Stepper estilo HyprMod: [ - ]  <val>  [ + ]
            return f"[ - ]  {str(val):>3}  [ + ]"

        elif item.item_type == "toggle":
            # Toggle cuadrado estilo widget de terminal
            return "[ ■ ] ON" if val else "[   ] off"

        elif item.item_type == "slider":
            # Slider estilo barra lineal recta
            pct = int(((val - item.min_val) / max(0.001, item.max_val - item.min_val)) * 10)
            pct = max(0, min(10, pct))
            bar = "─" * pct + "●" + "─" * (10 - pct)
            if isinstance(val, float):
                return f"{bar}  {val:.2f}"
            return f"{bar}  {val}"

        elif item.item_type == "select":
            # Select estilo rectangular
            return f"[ {val} v ]"

        elif item.item_type == "action":
            return "[ EJECUTAR ]"

        return str(val)

    def _get_item_value(self, item: SectionItem) -> Any:
        """Obtiene el valor actual de la variable en memoria."""
        key = item.key

        if key == "general:gaps_in":
            return self.settings.get("gaps_in", 5)
        if key == "general:gaps_out":
            return self.settings.get("gaps_out", 10)
        if key == "general:border_size":
            return self.settings.get("border_size", 2)
        if key == "general:resize_on_border":
            return self.settings.get("resize_on_border", True)
        if key == "general:layout":
            return self.settings.get("layout", "dwindle")
        if key == "general:allow_tearing":
            return self.settings.get("allow_tearing", False)
        if key == "general:snap:enabled":
            return self.settings.get("snap_enabled", False)

        if key == "decoration:rounding":
            return self.settings.get("rounding", 8)
        if key == "decoration:active_opacity":
            return self.settings.get("active_opacity", 1.0)
        if key == "decoration:inactive_opacity":
            return self.settings.get("inactive_opacity", 0.95)
        if key == "decoration:dim_inactive":
            return self.settings.get("dim_inactive", False)
        if key == "decoration:dim_strength":
            return self.settings.get("dim_strength", 0.15)
        if key == "decoration:blur:enabled":
            return self.settings.get("blur_enabled", True)
        if key == "decoration:blur:size":
            return self.settings.get("blur_size", 5)
        if key == "decoration:blur:passes":
            return self.settings.get("blur_passes", 2)
        if key == "decoration:shadow:enabled":
            return self.settings.get("shadow_enabled", True)

        if key == "animations:enabled":
            return self.settings.get("animations_enabled", True)
        if key == "animations:preset":
            return self.settings.get("animation_preset", "smooth")
        if key == "animations:windows":
            return self.settings.get("anim_windows", "popin 80%")
        if key == "animations:workspaces":
            return self.settings.get("anim_workspaces", "slide")

        if key == "cursor:no_hardware_cursors":
            return self.settings.get("no_hw_cursors", False)
        if key == "cursor:inactive_timeout":
            return self.settings.get("cursor_timeout", 0)
        if key == "cursor:zoom_factor":
            return self.settings.get("cursor_zoom", 1.0)

        if key == "input:compose_key":
            return "Alt Gr (Compose) [Normal]" if self.settings.get("compose_key") == "ralt" else "Bloq Mayús (Compose)"
        if key == "input:repeat_rate":
            return self.settings.get("repeat_rate", 40)
        if key == "input:repeat_delay":
            return self.settings.get("repeat_delay", 250)
        if key == "input:numlock_by_default":
            return self.settings.get("numlock", True)

        if key == "input:sensitivity":
            return self.settings.get("sensitivity", 0.0)
        if key == "input:accel_profile":
            return self.settings.get("accel_profile", "flat")
        if key == "input:touchpad:natural_scroll":
            return self.settings.get("natural_scroll", False)
        if key == "input:touchpad:clickfinger_behavior":
            return self.settings.get("clickfinger", True)
        if key == "input:touchpad:tap-to-click":
            return self.settings.get("tap_to_click", True)
        if key == "input:touchpad:disable_while_typing":
            return self.settings.get("disable_typing", True)
        if key == "gestures:workspace_swipe":
            return self.settings.get("workspace_swipe", True)

        if key == "display:scale":
            return f"{self.monitors[0].get('scale', 1.0)}x" if self.monitors else "1x"
        if key == "display:mode":
            if self.monitors:
                m = self.monitors[0]
                return f"{m.get('width')}x{m.get('height')}@{m.get('refreshRate', 60):.0f}Hz"
            return "1920x1080@60Hz"

        if key == "omarchy:theme":
            return self.theme_engine.current_theme
        if key == "omarchy:icons":
            return "Lizarbe-Red"

        return self.settings.get(key, "-")

    # ==========================
    # MANEJO DE ENTRADA Y RATÓN
    # ==========================

    def handle_input(self, fd: int) -> None:
        r, _, _ = select.select([fd], [], [], 0.05)
        if not r:
            return

        ch = os.read(fd, 128)
        if not ch:
            return

        # Comprobar secuencias de ratón en formato extendido SGR (\x1b[<btn;x;yM/m)
        mouse_matches = list(re.finditer(b"\x1b\\[<(\\d+);(\\d+);(\\d+)([Mm])", ch))
        if mouse_matches:
            for m in mouse_matches:
                btn = int(m.group(1))
                x = int(m.group(2))
                y = int(m.group(3))
                act = m.group(4)
                self._handle_mouse_event(btn, x, y, act)
            return

        # Salir con q o Esc
        if ch in (b"q", b"Q", b"\x1b") and len(ch) == 1:
            self.running = False
            return

        # Cambiar foco con Tab, Shift+Tab o h / l
        if ch in (b"\t", b"\x1b[Z"):
            self.active_pane = "content" if self.active_pane == "sidebar" else "sidebar"
            return

        # Guardar rápido con 's'
        if ch in (b"s", b"S"):
            self.save_all()
            return

        # Navegación izquierda/derecha entre columnas
        if ch == b"\x1b[D":  # Flecha Izquierda
            if self.active_pane == "content":
                self._adjust_current_item(delta=-1)
            else:
                self.active_pane = "sidebar"
            return

        if ch == b"\x1b[C":  # Flecha Derecha
            if self.active_pane == "content":
                self._adjust_current_item(delta=1)
            else:
                self.active_pane = "content"
            return

        # Navegación vertical arriba/abajo
        if ch == b"\x1b[A":  # Flecha Arriba
            if self.active_pane == "sidebar":
                self.current_section_idx = max(0, self.current_section_idx - 1)
                self.selected_item_idx = 0
            else:
                self.selected_item_idx = max(0, self.selected_item_idx - 1)
            return

        if ch == b"\x1b[B":  # Flecha Abajo
            if self.active_pane == "sidebar":
                self.current_section_idx = min(len(self.SECTIONS) - 1, self.current_section_idx + 1)
                self.selected_item_idx = 0
            else:
                sec_id = self.SECTIONS[self.current_section_idx][1]
                items_len = len(self.section_items.get(sec_id, []))
                self.selected_item_idx = min(items_len - 1, self.selected_item_idx + 1)
            return

        # Enter o Espacio para activar/conmutar
        if ch in (b"\r", b"\n", b" "):
            if self.active_pane == "sidebar":
                self.active_pane = "content"
            else:
                self._activate_current_item()
            return

    def _handle_mouse_event(self, btn: int, x: int, y: int, act: bytes) -> None:
        """Procesa clics, arrastres y rueda del ratón."""
        cols, rows = shutil.get_terminal_size((90, 26))
        sidebar_w = 26

        if act == b"M":
            # 1. Clic Izquierdo (btn == 0)
            if btn == 0:
                # Clic en barra de título superior
                if y == 1:
                    if x >= cols - 12:  # Botón "q: Salir"
                        self.running = False
                    return

                # Clic en barra inferior de estado
                if y == rows:
                    if x >= cols - 24 and x <= cols - 12:  # "[s]: Guardar"
                        self.save_all()
                    elif x > cols - 12:  # "[q]: Salir"
                        self.running = False
                    elif x <= 24:  # "[Tab]: Cambiar foco"
                        self.active_pane = "content" if self.active_pane == "sidebar" else "sidebar"
                    return

                # Clic en barra lateral izquierda (Sidebar)
                if x <= sidebar_w:
                    sec_idx = self._sidebar_click_map.get(y)
                    if sec_idx is not None:
                        self.current_section_idx = sec_idx
                        self.selected_item_idx = 0
                        self.active_pane = "content"
                    return

                # Clic en panel de contenido (Content)
                if x > sidebar_w + 1:
                    info = self._content_click_map.get(y)
                    if info:
                        self.active_pane = "content"
                        self.selected_item_idx = info["item_idx"]
                        item = info["item"]

                        if item.item_type == "stepper":
                            m_start, m_end = info["minus_range"]
                            p_start, p_end = info["plus_range"]
                            if m_start <= x <= m_end:
                                self._adjust_current_item(delta=-1)
                            elif p_start <= x <= p_end:
                                self._adjust_current_item(delta=1)

                        elif item.item_type == "toggle":
                            self._activate_current_item()

                        elif item.item_type == "select":
                            self._adjust_current_item(delta=1)

                        elif item.item_type == "slider":
                            s_start, s_end = info["slider_range"]
                            if s_start <= x <= s_end:
                                ratio = (x - s_start) / max(1, s_end - s_start)
                                ratio = max(0.0, min(1.0, ratio))
                                new_val = item.min_val + ratio * (item.max_val - item.min_val)
                                if isinstance(item.step, int) or (isinstance(item.min_val, int) and isinstance(item.max_val, int)):
                                    new_val = round(new_val)
                                else:
                                    new_val = round(new_val, 2)
                                new_val = max(item.min_val, min(item.max_val, new_val))
                                self._set_item_value(item.key, new_val)
                                self._apply_hyprctl_live(item.key, new_val)

                        elif item.item_type == "action":
                            c_start, c_end = info["control_range"]
                            if c_start <= x <= c_end:
                                self._activate_current_item()

            # 2. Arrastre con clic izquierdo sostenido (btn == 32)
            elif btn == 32:
                if x > sidebar_w + 1:
                    info = self._content_click_map.get(y)
                    if info and info["item"].item_type == "slider":
                        item = info["item"]
                        s_start, s_end = info["slider_range"]
                        ratio = (x - s_start) / max(1, s_end - s_start)
                        ratio = max(0.0, min(1.0, ratio))
                        new_val = item.min_val + ratio * (item.max_val - item.min_val)
                        if isinstance(item.step, int) or (isinstance(item.min_val, int) and isinstance(item.max_val, int)):
                            new_val = round(new_val)
                        else:
                            new_val = round(new_val, 2)
                        new_val = max(item.min_val, min(item.max_val, new_val))
                        self._set_item_value(item.key, new_val)
                        self._apply_hyprctl_live(item.key, new_val)

            # 3. Rueda del ratón hacia arriba (Scroll Up: btn == 64)
            elif btn == 64:
                if x <= sidebar_w:
                    self.current_section_idx = max(0, self.current_section_idx - 1)
                    self.selected_item_idx = 0
                else:
                    info = self._content_click_map.get(y)
                    if info and info["item"].item_type in ("stepper", "slider"):
                        self.selected_item_idx = info["item_idx"]
                        self._adjust_current_item(delta=1)
                    else:
                        self.selected_item_idx = max(0, self.selected_item_idx - 1)

            # 4. Rueda del ratón hacia abajo (Scroll Down: btn == 65)
            elif btn == 65:
                if x <= sidebar_w:
                    self.current_section_idx = min(len(self.SECTIONS) - 1, self.current_section_idx + 1)
                    self.selected_item_idx = 0
                else:
                    info = self._content_click_map.get(y)
                    if info and info["item"].item_type in ("stepper", "slider"):
                        self.selected_item_idx = info["item_idx"]
                        self._adjust_current_item(delta=-1)
                    else:
                        sec_id = self.SECTIONS[self.current_section_idx][1]
                        items_len = len(self.section_items.get(sec_id, []))
                        self.selected_item_idx = min(items_len - 1, self.selected_item_idx + 1)

    def _adjust_current_item(self, delta: int) -> None:
        """Modifica el valor del elemento seleccionado con flechas izquierda/derecha."""
        sec_id = self.SECTIONS[self.current_section_idx][1]
        items = self.section_items.get(sec_id, [])
        if not items or self.selected_item_idx >= len(items):
            return

        item = items[self.selected_item_idx]

        if item.item_type in ("stepper", "slider"):
            cur = self._get_item_value(item)
            new_val = cur + (item.step * delta)
            if isinstance(item.step, float):
                new_val = round(new_val, 2)
            new_val = max(item.min_val, min(item.max_val, new_val))
            self._set_item_value(item.key, new_val)
            self._apply_hyprctl_live(item.key, new_val)

        elif item.item_type == "select" and item.options:
            cur = str(self._get_item_value(item))
            try:
                idx = item.options.index(cur)
            except ValueError:
                idx = 0
            next_idx = (idx + delta) % len(item.options)
            chosen = item.options[next_idx]
            self._set_item_value(item.key, chosen)
            self._apply_hyprctl_live(item.key, chosen)

        elif item.item_type == "toggle":
            cur = bool(self._get_item_value(item))
            self._set_item_value(item.key, not cur)
            self._apply_hyprctl_live(item.key, not cur)

    def _activate_current_item(self) -> None:
        """Ejecuta la acción o conmuta el toggle del elemento seleccionado."""
        sec_id = self.SECTIONS[self.current_section_idx][1]
        items = self.section_items.get(sec_id, [])
        if not items or self.selected_item_idx >= len(items):
            return

        item = items[self.selected_item_idx]

        if item.item_type == "toggle":
            self._adjust_current_item(delta=1)
        elif item.item_type == "select":
            self._adjust_current_item(delta=1)
        elif item.item_type == "action":
            self._execute_action(item.key)

    def _set_item_value(self, key: str, val: Any) -> None:
        """Guarda el valor en la estructura de ajustes en memoria."""
        if key == "general:gaps_in":
            self.settings["gaps_in"] = int(val)
        elif key == "general:gaps_out":
            self.settings["gaps_out"] = int(val)
        elif key == "general:border_size":
            self.settings["border_size"] = int(val)
        elif key == "general:layout":
            self.settings["layout"] = str(val)
        elif key == "decoration:rounding":
            self.settings["rounding"] = int(val)
        elif key == "decoration:dim_inactive":
            self.settings["dim_inactive"] = bool(val)
        elif key == "decoration:dim_strength":
            self.settings["dim_strength"] = float(val)
        elif key == "animations:enabled":
            self.settings["animations_enabled"] = bool(val)
        elif key == "animations:preset":
            self.settings["animation_preset"] = str(val)
        elif key == "input:sensitivity":
            self.settings["sensitivity"] = float(val)
        elif key == "input:accel_profile":
            self.settings["accel_profile"] = str(val)
        elif key == "input:touchpad:natural_scroll":
            self.settings["natural_scroll"] = bool(val)
        elif key == "input:compose_key":
            self.settings["compose_key"] = "ralt" if "Alt Gr" in str(val) else "caps"
        elif key == "display:scale":
            if self.monitors:
                scale_float = float(str(val).replace("x", ""))
                self.monitors[0]["scale"] = scale_float
        elif key == "omarchy:theme":
            self.status_message = f"Aplicando tema {val}..."
            self.render()
            self.theme_engine.set_theme(str(val))
            self.status_message = f"✓ Tema {val} aplicado."
        else:
            self.settings[key] = val

    def _apply_hyprctl_live(self, key: str, val: Any) -> None:
        """Aplica la variable en caliente a Hyprland si corresponde."""
        hypr_map = {
            "general:gaps_in": "general:gaps_in",
            "general:gaps_out": "general:gaps_out",
            "general:border_size": "general:border_size",
            "general:layout": "general:layout",
            "decoration:rounding": "decoration:rounding",
            "decoration:dim_inactive": "decoration:dim_inactive",
            "decoration:blur:enabled": "decoration:blur:enabled",
            "animations:enabled": "animations:enabled",
            "input:sensitivity": "input:sensitivity",
            "input:accel_profile": "input:accel_profile",
            "input:touchpad:natural_scroll": "input:touchpad:natural_scroll",
        }
        if key in hypr_map:
            HyprIPC.set_keyword(hypr_map[key], val)

    def _execute_action(self, action_key: str) -> None:
        """Ejecuta acciones especiales como guardar, liberar Bloq Mayús o setup."""
        if action_key == "action:fix_caps":
            use_ralt = (self.settings.get("compose_key", "ralt") == "ralt")
            self.config_sync.fix_caps_lock(use_ralt=use_ralt)
            self.status_message = "✓ Tecla Bloq Mayús LIBERADA (Compose reasignada a Alt Gr)."

        elif action_key == "action:save_monitor":
            if self.monitors:
                m = self.monitors[0]
                res = f"{m.get('width')}x{m.get('height')}"
                hz = float(m.get('refreshRate', 60.0))
                scale = float(m.get('scale', 1.0))
                ok = self.config_sync.save_monitor_config(m.get('name'), res, hz, scale)
                self.status_message = "✓ Configuración de monitor guardada en monitors.lua." if ok else "Error al guardar monitor."

        elif action_key == "action:apply_lizarbe_full":
            self.status_message = "Configurando Setup Lizarbe..."
            self.render()
            LizarbeManager.apply_lizarbe_theme("lizarbe")
            LizarbeManager.ensure_fastfetch_logo()
            self.config_sync.fix_caps_lock(use_ralt=True)
            self.install_update_hook()
            self.theme_engine.reload()
            self.status_message = "✓ ¡Setup Lizarbe Oficial aplicado al 100%!"

        elif action_key == "action:install_hook":
            self.install_update_hook()

    def save_all(self) -> None:
        """Guarda todas las opciones en hyprland-gui.lua y aplica live."""
        ok = self.config_sync.save_gui_settings(self.settings, apply_live=True)
        if ok:
            self.status_message = "✓ Ajustes guardados en ~/.config/hypr/hyprland-gui.lua."
        else:
            self.status_message = "Error al guardar configuración."

    def install_update_hook(self) -> None:
        hook_dir = Path.home() / ".config" / "omarchy" / "hooks" / "post-update.d"
        hook_dir.mkdir(parents=True, exist_ok=True)
        hook_file = hook_dir / "99-meca-hyprconfig.sh"
        
        script_dir = Path(__file__).resolve().parent.parent.parent
        hook_content = f"""#!/usr/bin/env bash
set -e
REPO_DIR="{script_dir}"
if [[ -d "$REPO_DIR/.git" ]] && command -v git &>/dev/null; then
    echo "[MECA] Comprobando actualizaciones de Meca HyprConfig..."
    git -C "$REPO_DIR" pull --ff-only 2>/dev/null || true
fi
if command -v meca &>/dev/null; then
    meca --fix-caps &>/dev/null || true
fi
exit 0
"""
        try:
            hook_file.write_text(hook_content, encoding="utf-8")
            hook_file.chmod(0o755)
            self.status_message = "✓ Hook instalado en ~/.config/omarchy/hooks/post-update.d/99-meca-hyprconfig.sh."
        except Exception:
            self.status_message = "Error al instalar el hook."
