"""
Interfaz TUI Monolítica para Meca HyprConfig (Estilo HyprMod / GNOME / macOS).
Arquitectura de 2 paneles (Categorías a la izquierda, Variables de Hyprland a la derecha),
con soporte completo de ratón, controles en cuadrados cerrados, modales interactivos,
gestión de Autostart y edición de temas de Omarchy.
"""

from __future__ import annotations
import os
import re
import sys
import tty
import termios
import select
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from meca.core.theme_engine import ThemeEngine
from meca.core.hypr_ipc import HyprIPC
from meca.core.config_sync import ConfigSync
from meca.core.lizarbe_manager import LizarbeManager


class SectionItem:
    """Representa una variable o control configurable dentro de una sección."""
    def __init__(
        self,
        key: str,
        name: str,
        desc: str,
        item_type: str,  # "stepper", "toggle", "select", "slider", "action"
        min_val: float = 0,
        max_val: float = 100,
        step: float = 1,
        options: Optional[List[str]] = None,
    ):
        self.key = key
        self.name = name
        self.desc = desc
        self.item_type = item_type
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.options = options or []


class MecaTUI:
    """
    Panel de Configuración Monolítico inspirado en HyprMod / GNOME Settings.
    Solo utiliza glifos Nerd Font en la barra lateral izquierda. Sin emojis.
    """

    # Secciones organizadas por grupos con iconos solo en la barra izquierda
    SECTIONS = [
        ("LOOK & FEEL", "general", "", "General", "Gaps, bordes, layout y comportamiento general"),
        ("LOOK & FEEL", "decoration", "", "Decoration", "Redondeo de esquinas, desenfoque, opacidad y sombras"),
        ("LOOK & FEEL", "animations", "", "Animations", "Velocidad, curvas y transiciones de ventanas"),
        ("LOOK & FEEL", "cursor", "󰍽", "Cursor", "Hardware cursor, ocultación y factor de zoom"),
        ("INPUT", "keybinds", "", "Keybinds", "Tecla Compose (Bloq Mayús), repetición y atajos"),
        ("INPUT", "devices", "󰍽", "Devices", "Sensibilidad de ratón, aceleración y gestos touchpad"),
        ("DISPLAY", "monitors", "󰍹", "Monitors", "Escala HiDPI, resolución y frecuencia de refresco"),
        ("DISPLAY", "workspaces", "󰕰", "Workspaces", "Escritorios persistentes y modo de distribución"),
        ("WINDOW MANAGEMENT", "layouts", "󰕮", "Layouts", "Opciones de mosaico Dwindle, Master y Scrolling"),
        ("WINDOW MANAGEMENT", "rules", "", "Window Rules", "Reglas de ventanas flotantes y opacidad"),
        ("STARTUP & EXTRAS", "autostart", "", "Autostart", "Agregar aplicaciones, servicios o comandos al inicio"),
        ("STARTUP & EXTRAS", "omarchy", "󰚰", "Omarchy", "Temas, edicion de paleta, servicios y ajustes de Omarchy"),
    ]

    def __init__(self):
        self.theme_engine = ThemeEngine()
        self.config_sync = ConfigSync()
        self.running = True

        # Navegación de paneles: "sidebar" (izquierda), "content" (derecha) o "buttons" (barra inferior)
        self.active_pane = "sidebar"
        self.current_section_idx = 0
        self.selected_item_idx = 0
        self.content_scroll_offset = 0
        self.status_message = "Listo. Usa el raton o las flechas para configurar Hyprland y Omarchy."

        # Datos cargados del sistema
        self.settings = self.config_sync.load_gui_settings()
        self.monitors = HyprIPC.get_monitors()
        self.available_themes = self.theme_engine.list_available_themes()
        self.autostart_items = self.config_sync.load_autostart_items()

        # Sincronizar propiedades del tema Omarchy activo dentro de settings para edición
        self._sync_theme_into_settings()
        self._sync_autostart_into_settings()

        # Escalas soportadas para monitores
        self.scales = ["1x", "1.25x", "1.5x", "1.75x", "2x"]
        self.scale_values = [1.0, 1.25, 1.5, 1.75, 2.0]

        # Copia de seguridad del estado guardado para detectar cambios pendientes al cambiar de sección
        self.saved_settings = dict(self.settings)
        self.saved_autostart = [dict(x) for x in self.autostart_items]
        self._was_tiled = False

        # Estado de ventana modal:
        # None | "confirm_section_change" | "confirm_reset" | "input_autostart" | "input_theme_hex"
        self.modal_state: Optional[str] = None
        self.modal_selected_idx: int = 0
        self.pending_section_idx: Optional[int] = None
        self.pending_focus_content: bool = False
        self._modal_button_click_map: Dict[int, Tuple[int, int]] = {}
        self._modal_button_row_range: Tuple[int, int] = (0, 0)

        # Estado de entrada de texto para modales interactivos (Autostart y Hex de Tema)
        self.modal_input_text: str = ""
        self.modal_input_kind: str = "launch"  # "launch" (App/Servicio) | "exec" (Comando)
        self.modal_hex_target: str = "accent"  # "accent" | "background" | "foreground" | "selection"
        self._modal_kind_click_range: Tuple[int, int, int] = (0, 0, 0)  # (y, x_min, x_max)

        # Mapeos de coordenadas para interacción con el ratón y estado hover (pasar el cursor)
        self._sidebar_click_map: Dict[int, int] = {}
        self._content_click_map: Dict[int, Dict[str, Any]] = {}
        self._button_click_map: Dict[str, Tuple[int, int]] = {}
        self._button_row_range: Tuple[int, int] = (0, 0)
        self.selected_button_idx = 2  # 0: Restablecer, 1: Cancelar, 2: Aplicar
        self.hover_sidebar_idx: Optional[int] = None
        self.hover_item_idx: Optional[int] = None
        self.hover_subcontrol: Optional[str] = None
        self.hover_button_key: Optional[str] = None
        self.hover_modal_btn_idx: Optional[int] = None

        # Inicializar definiciones de variables por sección
        self.section_items = self._init_section_items()

    def _sync_theme_into_settings(self) -> None:
        """Sincroniza los colores, modo e iconos del tema Omarchy activo hacia self.settings."""
        self.settings["omarchy_theme_name"] = self.theme_engine.current_theme
        self.settings["omarchy_theme_mode"] = self.theme_engine.mode
        self.settings["omarchy_theme_accent"] = self.theme_engine.colors.get("accent", "#E31B23")
        self.settings["omarchy_theme_bg"] = self.theme_engine.colors.get("background", "#08080B")
        self.settings["omarchy_theme_fg"] = self.theme_engine.colors.get("foreground", "#d8d8d8")
        self.settings["omarchy_theme_sel"] = self.theme_engine.colors.get("selection", "#45475a")
        self.settings["omarchy_icons"] = self.theme_engine.icon_theme

    def _sync_autostart_into_settings(self) -> None:
        """Sincroniza el estado de cada entrada de autostart dentro de self.settings."""
        for idx, entry in enumerate(self.autostart_items):
            self.settings[f"autostart_entry_{idx}"] = bool(entry.get("enabled", False))

    def _build_autostart_section_items(self) -> List[SectionItem]:
        """Construye dinámicamente los controles de la sección Autostart."""
        items = [
            SectionItem(
                "action:add_autostart",
                "Agregar aplicacion, servicio o comando",
                "Abre una ventana para registrar un nuevo proceso en ~/.config/hypr/autostart.lua",
                "action",
            ),
        ]
        for idx, entry in enumerate(self.autostart_items):
            cmd = entry.get("cmd", "")
            kind = entry.get("kind", "launch")
            kind_lbl = "App / Servicio (o.launch_on_start)" if kind == "launch" else "Comando (o.exec_on_start)"
            items.append(
                SectionItem(
                    f"autostart:item:{idx}",
                    cmd,
                    f"{kind_lbl} — Supr/Del para eliminar",
                    "toggle",
                )
            )
        return items

    def _init_section_items(self) -> Dict[str, List[SectionItem]]:
        themes = self.available_themes if self.available_themes else ["rose-pine", "lizarbe", "white", "catppuccin"]
        cur_accent = self.settings.get("omarchy_theme_accent", "#E31B23")
        accent_opts = [cur_accent, "#E31B23", "#89b4fa", "#1e66f5", "#2DB872", "#E5A83B", "#f38ba8", "#94e2d5", "#6e6e6e"]
        accent_opts = list(dict.fromkeys(accent_opts))

        cur_bg = self.settings.get("omarchy_theme_bg", "#08080B")
        bg_opts = list(dict.fromkeys([cur_bg, "#08080B", "#1e1e2e", "#161622", "#101019", "#ffffff", "#eff1f5"]))

        cur_fg = self.settings.get("omarchy_theme_fg", "#d8d8d8")
        fg_opts = list(dict.fromkeys([cur_fg, "#d8d8d8", "#cdd6f4", "#ffffff", "#000000", "#1a1a1a"]))

        cur_sel = self.settings.get("omarchy_theme_sel", "#45475a")
        sel_opts = list(dict.fromkeys([cur_sel, "#45475a", "#E31B23", "#c0c0c0", "#ccd0da", "#313244"]))

        cur_icons = self.settings.get("omarchy_icons", "Adwaita")
        icon_opts = list(dict.fromkeys([cur_icons, "Yaru-blue", "Yaru-red", "Papirus-Dark", "Adwaita", "Lizarbe-Red"]))

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
                SectionItem("input:compose_key", "Tecla Bloq Mayús", "Alt Gr = Compose (Bloq Mayús normal) vs Omarchy default", "select", options=["Alt Gr (Compose)", "Bloq Mayús (Compose)"]),
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
                SectionItem("display:mode", "Display resolution & Hz", "Modo y frecuencia de actualización del monitor", "select", options=["1920x1080@60Hz", "1920x1080@75Hz", "2560x1440@144Hz", "1280x720@60Hz"]),
                SectionItem("action:save_monitor", "Aplicar configuración de monitor", "Escribe los cambios en ~/.config/hypr/monitors.lua", "action"),
            ],
            "workspaces": [
                SectionItem("workspace:count", "Persistent workspaces", "Cantidad de escritorios fijos en la barra", "stepper", 1, 10, 1),
                SectionItem("workspace:layout_toggle", "Workspace layout", "Alternar entre modo dwindle o modo niri (scrolling)", "select", options=["dwindle", "scrolling"]),
            ],
            "layouts": [
                SectionItem("dwindle:force_split", "Force split", "Dirección de división (0=ratón, 1=izq/arriba, 2=der/abajo)", "stepper", 0, 2, 1),
                SectionItem("dwindle:preserve_split", "Preserve split", "Mantiene la dirección de división al cerrar ventanas", "toggle"),
                SectionItem("dwindle:smart_split", "Smart split", "Determina división según posición del cursor", "toggle"),
                SectionItem("master:new_status", "Master new status", "Ubicación de ventanas recién creadas (master / slave)", "select", options=["master", "slave"]),
            ],
            "rules": [
                SectionItem("rules:pavucontrol_float", "Float Pavucontrol", "Abre el panel de audio Pavucontrol como ventana flotante", "toggle"),
                SectionItem("rules:calculator_float", "Float Calculator", "Abre la calculadora en modo flotante centrado", "toggle"),
            ],
            "autostart": self._build_autostart_section_items(),
            "omarchy": [
                SectionItem("omarchy:theme", "Active Omarchy Theme", "Selecciona y aplica el tema global de Omarchy", "select", options=themes),
                SectionItem("omarchy:theme_mode", "Theme mode (dark/light)", "Edita el modo en el tema actual y en el tema original", "select", options=["dark", "light"]),
                SectionItem("omarchy:theme_accent", "Theme accent color", "Edita el color de acento en el tema actual y original", "select", options=accent_opts),
                SectionItem("omarchy:theme_bg", "Theme background color", "Edita el color de fondo en el tema actual y original", "select", options=bg_opts),
                SectionItem("omarchy:theme_fg", "Theme foreground color", "Edita el color de texto en el tema actual y original", "select", options=fg_opts),
                SectionItem("omarchy:theme_sel", "Theme selection color", "Edita el color de seleccion en el tema actual y original", "select", options=sel_opts),
                SectionItem("omarchy:icons", "Icon Theme", "Edita el paquete de iconos en icons.theme del tema", "select", options=icon_opts),
                SectionItem("action:custom_theme_hex", "Escribir color Hex personalizado", "Ingresa un codigo #RRGGBB exacto para editar el tema", "action"),
                SectionItem("action:next_wallpaper", "Cambiar fondo de pantalla", "Alterna al siguiente wallpaper del tema Omarchy activo", "action"),
                SectionItem("action:toggle_bar", "Alternar barra superior Omarchy", "Muestra u oculta la barra superior de Omarchy", "action"),
                SectionItem("action:toggle_nightlight", "Alternar luz nocturna", "Activa o desactiva el filtro cálido hyprsunset", "action"),
                SectionItem("action:apply_lizarbe_full", "Aplicar Setup Lizarbe", "Configura el tema Lizarbe, logo Fastfetch y Bloq Mayús", "action"),
                SectionItem("action:install_hook", "Registrar hook en 'omarchy update'", "Mantiene Meca sincronizado al actualizar el sistema", "action"),
            ],
        }

    def run(self) -> None:
        """Ciclo principal TUI en modo crudo y ventana flotante centrada."""
        if not sys.stdin.isatty():
            print("Error: meca debe ejecutarse en una terminal TTY.")
            return

        # Convertir la ventana de terminal activa en flotante y centrada
        self._was_tiled = HyprIPC.ensure_floating_centered(width=960, height=680)

        fd = sys.stdin.fileno()
        self.orig_termios = termios.tcgetattr(fd)

        try:
            tty.setraw(fd)
            # Alternate screen buffer, ocultar cursor, desactivar auto-wrap (?7l) y habilitar ratón SGR con hover (?1003h)
            sys.stdout.write("\033[?1049h\033[?25l\033[?7l\033[?1000h\033[?1002h\033[?1003h\033[?1006h\033[2J")
            sys.stdout.flush()

            while self.running:
                self.render()
                self.handle_input(fd)
        finally:
            # Deshabilitar ratón y hover, reactivar auto-wrap (?7h), mostrar cursor y salir de alternate buffer
            sys.stdout.write("\033[?1006l\033[?1003l\033[?1002l\033[?1000l\033[?7h\033[?25h\033[?1049l\033[0m")
            sys.stdout.flush()
            if self.orig_termios:
                termios.tcsetattr(fd, termios.TCSADRAIN, self.orig_termios)
            if self._was_tiled:
                HyprIPC.restore_tiled()

    # ==========================
    # RENDERIZADO CON POSICIONAMIENTO EXACTO
    # ==========================

    def render(self) -> None:
        cols, rows = shutil.get_terminal_size((90, 26))
        sidebar_w = 26
        content_w = max(30, cols - sidebar_w - 1)
        buf: List[str] = []

        # 1. Barra de Título Superior en fila exacta 1 (\033[1;1H)
        ver = HyprIPC.get_version_info()
        title_left = " MECA HyprConfig "
        unsaved_badge = " *CAMBIOS PENDIENTES* | " if self.has_unsaved_changes() else ""
        title_right = f"{unsaved_badge}Hyprland {ver} | Tema: {self.theme_engine.current_theme} | q: Salir "
        space_len = max(0, cols - len(title_left) - len(title_right))
        header_line = (title_left + (" " * space_len) + title_right)[:cols]
        buf.append(f"\033[1;1H" + self.theme_engine.style("bright_foreground", "accent", header_line, bold=True) + "\033[K")

        # 2. Cuerpo Dividido (Filas 2 a rows - 1)
        body_rows = max(10, rows - 2)
        sidebar_lines = self._render_sidebar(sidebar_w, body_rows)
        content_lines = self._render_content(content_w, body_rows, sidebar_w)

        sep_styled = self.theme_engine.fg("muted", "│")
        for r in range(body_rows):
            screen_y = r + 2
            s_line = sidebar_lines[r] if r < len(sidebar_lines) else (" " * sidebar_w)
            c_line = content_lines[r] if r < len(content_lines) else ""
            buf.append(f"\033[{screen_y};1H{s_line}")
            buf.append(f"\033[{screen_y};{sidebar_w + 1}H{sep_styled}")
            buf.append(f"\033[{screen_y};{sidebar_w + 2}H{c_line}\033[K")

        # 3. Barra Inferior de Estado en fila exacta 'rows' (sin corchetes, truncada a cols - 1)
        keys_hint = " Tab: Foco │ r: Restablecer │ c: Cancelar │ a: Aplicar │ q: Salir "
        if cols < 95:
            keys_hint = " r:Restablecer │ c:Cancelar │ a:Aplicar │ q:Salir "
        max_status_w = max(8, cols - len(keys_hint) - 1)
        status_txt = f" {self.status_message}"[:max_status_w]
        footer_space = max(0, cols - 1 - len(status_txt) - len(keys_hint))
        footer_line = (status_txt + (" " * footer_space) + keys_hint)[:cols - 1]
        buf.append(f"\033[{rows};1H" + self.theme_engine.style("bright_foreground", "muted", footer_line) + "\033[K")

        # 4. Ventana Modal (si está activa)
        if self.modal_state:
            buf.extend(self._render_modal_overlay(cols, rows))

        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    def _render_sidebar(self, width: int, max_rows: int) -> List[str]:
        """
        Renderiza el panel izquierdo con mayor margen vertical entre categorías y secciones.
        Registra las filas exactas en self._sidebar_click_map para precisión de clic 1:1.
        """
        lines: List[str] = []
        current_cat = None
        self._sidebar_click_map.clear()

        # Si la terminal tiene suficiente altura, damos aún más respiro entre ítems
        extra_item_gap = max_rows >= 36

        for idx, (cat, sec_id, icon, title, desc) in enumerate(self.SECTIONS):
            if cat != current_cat:
                # Margen vertical antes de cada bloque de categoría
                if current_cat is not None and len(lines) < max_rows:
                    lines.append(" " * width)
                elif current_cat is None and max_rows >= 24 and len(lines) < max_rows:
                    lines.append(" " * width)

                current_cat = cat
                if len(lines) < max_rows:
                    lines.append(self.theme_engine.style("muted", None, f" {cat}".ljust(width)[:width], bold=True))

            if len(lines) >= max_rows:
                break

            is_sel = (idx == self.current_section_idx)
            is_hover = (idx == self.hover_sidebar_idx and not self.modal_state)
            is_active_pane = (self.active_pane == "sidebar" and not self.modal_state)

            screen_row = 2 + len(lines)
            self._sidebar_click_map[screen_row] = idx

            prefix = " ▸" if is_hover else "  "
            item_text = f"{prefix}{icon}  {title}".ljust(width)[:width]

            if is_sel and (is_active_pane or is_hover):
                line = self.theme_engine.style("bright_foreground", "selection", item_text, bold=True)
            elif is_sel:
                line = self.theme_engine.style("bright_foreground", "muted", item_text, bold=True)
            elif is_hover:
                line = self.theme_engine.style("bright_foreground", "muted", item_text, bold=True)
            else:
                line = self.theme_engine.style("foreground", None, item_text)

            lines.append(line)

            if extra_item_gap and len(lines) < max_rows:
                lines.append(" " * width)

        while len(lines) < max_rows:
            lines.append(" " * width)

        return lines[:max_rows]

    def _render_content(self, width: int, max_rows: int, sidebar_w: int) -> List[str]:
        lines: List[str] = []
        sec_meta = self.SECTIONS[self.current_section_idx]
        sec_id = sec_meta[1]
        sec_title = sec_meta[3]
        sec_desc = sec_meta[4]
        self._content_click_map.clear()

        # Encabezado de la Sección Activa (3 líneas: screen_y 2, 3, 4)
        lines.append(" " + self.theme_engine.style("bright_foreground", None, sec_title.upper(), bold=True))
        lines.append(" " + self.theme_engine.fg("muted", sec_desc[:width - 2]))
        lines.append(" " + self.theme_engine.fg("muted", "─" * max(1, width - 2)))

        if sec_id == "autostart":
            self.section_items["autostart"] = self._build_autostart_section_items()

        items = self.section_items.get(sec_id, [])
        is_active_pane = (self.active_pane == "content" and not self.modal_state)
        content_start_x = sidebar_w + 2

        # Reservamos las últimas 4 líneas para el separador (1) + botones compactos de 3 líneas
        buttons_block_h = 4
        items_area_rows = max(3, max_rows - 3 - buttons_block_h)
        max_visible_items = max(1, items_area_rows // 3)

        if self.selected_item_idx >= len(items):
            self.selected_item_idx = max(0, len(items) - 1)

        if self.selected_item_idx < self.content_scroll_offset:
            self.content_scroll_offset = self.selected_item_idx
        elif self.selected_item_idx >= self.content_scroll_offset + max_visible_items:
            self.content_scroll_offset = self.selected_item_idx - max_visible_items + 1
        self.content_scroll_offset = max(0, min(self.content_scroll_offset, max(0, len(items) - max_visible_items)))

        visible_end = min(len(items), self.content_scroll_offset + max_visible_items)

        for i in range(self.content_scroll_offset, visible_end):
            item = items[i]
            is_hover_row = (i == self.hover_item_idx and not self.modal_state)
            is_sel = (i == self.selected_item_idx and is_active_pane) or is_hover_row
            hover_sub = self.hover_subcontrol if is_hover_row else None

            c_top, c_mid, c_bot, ctrl_vis_w = self._format_item_control_3lines(item, is_sel, hover_sub)
            left_max_w = max(12, width - ctrl_vis_w - 3)

            item_screen_row = 2 + len(lines)
            control_x_start = content_start_x + left_max_w + 1
            control_x_end = control_x_start + ctrl_vis_w - 1

            click_info = {
                "item_idx": i,
                "item": item,
                "control_range": (control_x_start, control_x_end),
                "minus_range": (control_x_start, control_x_start + 4),
                "plus_range": (control_x_end - 4, control_x_end),
                "slider_range": (control_x_start, control_x_start + 10),
            }
            self._content_click_map[item_screen_row] = click_info
            self._content_click_map[item_screen_row + 1] = click_info
            self._content_click_map[item_screen_row + 2] = click_info

            if is_sel:
                l1_raw = f" ▌ {item.name}"[:left_max_w].ljust(left_max_w)
                l2_raw = f" ▌ └─ {item.desc}"[:left_max_w].ljust(left_max_w)
                l1_styled = self.theme_engine.style("bright_foreground", "selection", l1_raw, bold=True)
                l2_styled = self.theme_engine.fg("foreground", l2_raw)
            else:
                l1_raw = f"   {item.name}"[:left_max_w].ljust(left_max_w)
                l2_raw = f"   {item.desc}"[:left_max_w].ljust(left_max_w)
                l1_styled = self.theme_engine.style("bright_foreground", None, l1_raw, bold=True)
                l2_styled = self.theme_engine.fg("muted", l2_raw)

            l3_styled = " " * left_max_w

            lines.append(f"{l1_styled} {c_top}")
            lines.append(f"{l2_styled} {c_mid}")
            lines.append(f"{l3_styled} {c_bot}")

        # Rellenar espacio hasta la zona de botones
        target_before_buttons = max(3, max_rows - buttons_block_h)
        while len(lines) < target_before_buttons:
            lines.append("")

        # Separador antes de los botones físicos
        lines.append(" " + self.theme_engine.fg("muted", "─" * max(1, width - 2)))

        # Renderizar los 3 botones compactos y elegantes (3 líneas de alto)
        btn_top_screen_y = 2 + len(lines)
        btn_lines = self._render_3d_buttons(width, btn_top_screen_y, content_start_x)
        lines.extend(btn_lines)

        return lines[:max_rows]

    def _render_3d_buttons(self, width: int, btn_top_screen_y: int, content_start_x: int) -> List[str]:
        """
        Dibuja los 3 botones inferiores compactos de 3 líneas con bisel 3D Unicode:
          ┌─────────────┐  ┌──────────┐  ┌───────────┐
          ┃ Restablecer │  ┃ Cancelar │  ┃  Aplicar  │
          ┗━━━━━━━━━━━━━┙  ┗━━━━━━━━━━┙  ┗━━━━━━━━━━━┙
        """
        self._button_click_map.clear()
        self._button_row_range = (btn_top_screen_y, btn_top_screen_y + 2)

        buttons_spec = [
            ("reset", 0, " Restablecer "),
            ("cancel", 1, " Cancelar "),
            ("save", 2, "  Aplicar  "),
        ]

        gap = 2
        total_btns_w = sum(len(lbl) + 2 for _, _, lbl in buttons_spec) + gap * (len(buttons_spec) - 1)
        left_pad = max(2, width - total_btns_w - 2)

        row0_parts = [" " * left_pad]
        row1_parts = [" " * left_pad]
        row2_parts = [" " * left_pad]

        cur_rel_x = left_pad
        is_btn_pane = (self.active_pane == "buttons" and not self.modal_state)

        for btn_key, btn_idx, label in buttons_spec:
            inner_w = len(label)
            btn_w = inner_w + 2
            is_hover_btn = (self.hover_button_key == btn_key and not self.modal_state)
            is_sel = (is_btn_pane and self.selected_button_idx == btn_idx) or is_hover_btn
            is_primary = (btn_key == "save")

            abs_x_start = content_start_x + cur_rel_x
            abs_x_end = abs_x_start + btn_w - 1
            self._button_click_map[btn_key] = (abs_x_start, abs_x_end)

            border_col = "bright_foreground" if (is_sel or is_primary) else "foreground"
            bevel_col = "accent" if (is_sel or is_primary) else "muted"

            r0 = self.theme_engine.style(border_col, None, "┌" + ("─" * inner_w) + "┐", bold=(is_sel or is_primary))

            left_edge = self.theme_engine.style(bevel_col, None, "┃", bold=True)
            right_edge = self.theme_engine.style(border_col, None, "│", bold=(is_sel or is_primary))
            if is_hover_btn:
                inner_styled = self.theme_engine.style("bright_foreground", "accent", label, bold=True)
            elif is_sel:
                inner_styled = self.theme_engine.style("bright_foreground", "selection", label, bold=True)
            elif is_primary:
                inner_styled = self.theme_engine.style("bright_foreground", None, label, bold=True)
            else:
                inner_styled = self.theme_engine.style("foreground", None, label)
            r1 = f"{left_edge}{inner_styled}{right_edge}"

            r2 = self.theme_engine.style(bevel_col, None, "┗" + ("━" * inner_w) + "┙", bold=True)

            row0_parts.append(r0 + (" " * gap))
            row1_parts.append(r1 + (" " * gap))
            row2_parts.append(r2 + (" " * gap))

            cur_rel_x += btn_w + gap

        return [
            "".join(row0_parts),
            "".join(row1_parts),
            "".join(row2_parts),
        ]

    def _format_item_control_3lines(
        self,
        item: SectionItem,
        is_sel: bool,
        hover_sub: Optional[str] = None,
    ) -> Tuple[str, str, str, int]:
        """
        Dibuja los controles del panel derecho usando cuadrados cerrados reales
        de 3 líneas (┌───┐ / ┃ - │ / ┗━━━┙) en lugar de corchetes [ ], con respuesta al hover.
        """
        val = self._get_item_value(item)
        b_col = "bright_foreground" if is_sel else "foreground"
        sh_col = "accent" if is_sel else "muted"

        if item.item_type == "stepper":
            val_str = f"{str(val):^5}"[:5]
            m_hov = (hover_sub == "minus")
            p_hov = (hover_sub == "plus")

            top_m = self.theme_engine.style("accent" if m_hov else b_col, None, "┌───┐", bold=m_hov)
            top_p = self.theme_engine.style("accent" if p_hov else b_col, None, "┌───┐", bold=p_hov)
            bot_m = self.theme_engine.style("accent" if m_hov else sh_col, None, "┗━━━┙", bold=True)
            bot_p = self.theme_engine.style("accent" if p_hov else sh_col, None, "┗━━━┙", bold=True)

            m_bg = "accent" if m_hov else ("selection" if is_sel else None)
            p_bg = "accent" if p_hov else ("selection" if is_sel else None)

            m_mid = (
                self.theme_engine.fg("accent" if m_hov else sh_col, "┃")
                + self.theme_engine.style("bright_foreground", m_bg, " - ", bold=True)
                + self.theme_engine.fg(b_col, "│")
            )
            p_mid = (
                self.theme_engine.fg("accent" if p_hov else sh_col, "┃")
                + self.theme_engine.style("bright_foreground", p_bg, " + ", bold=True)
                + self.theme_engine.fg(b_col, "│")
            )
            val_mid = self.theme_engine.style("bright_foreground", None, val_str, bold=True)

            c_top = f"{top_m}     {top_p}"
            c_mid = f"{m_mid}{val_mid}{p_mid}"
            c_bot = f"{bot_m}     {bot_p}"
            return c_top, c_mid, c_bot, 15

        elif item.item_type == "toggle":
            is_on = bool(val)
            c_hov = (hover_sub == "control")
            box_top = self.theme_engine.style("accent" if c_hov else b_col, None, "┌───┐", bold=c_hov) + "    "
            mark = " ■ " if is_on else "   "
            state_lbl = " ON " if is_on else " off"
            mark_bg = "accent" if c_hov else ("selection" if (is_sel or is_on) else None)
            mark_styled = self.theme_engine.style(
                "bright_foreground" if (is_on or c_hov) else "muted",
                mark_bg,
                mark,
                bold=(is_on or c_hov),
            )
            lbl_styled = self.theme_engine.style("bright_foreground" if (is_on or c_hov) else "muted", None, state_lbl, bold=(is_on or c_hov))
            box_mid = (
                self.theme_engine.fg("accent" if c_hov else sh_col, "┃")
                + mark_styled
                + self.theme_engine.fg(b_col, "│")
                + lbl_styled
            )
            box_bot = self.theme_engine.fg("accent" if c_hov else sh_col, "┗━━━┙") + "    "
            return box_top, box_mid, box_bot, 9

        elif item.item_type == "select":
            raw_lbl = f" {val} ▾ "
            inner_w = len(raw_lbl)
            c_hov = (hover_sub == "control")
            c_top = self.theme_engine.style("accent" if c_hov else b_col, None, "┌" + ("─" * inner_w) + "┐", bold=c_hov)
            inner_bg = "accent" if c_hov else ("selection" if is_sel else None)
            inner_s = self.theme_engine.style("bright_foreground", inner_bg, raw_lbl, bold=(is_sel or c_hov))
            c_mid = self.theme_engine.fg("accent" if c_hov else sh_col, "┃") + inner_s + self.theme_engine.fg(b_col, "│")
            c_bot = self.theme_engine.fg("accent" if c_hov else sh_col, "┗" + ("━" * inner_w) + "┙")
            return c_top, c_mid, c_bot, inner_w + 2

        elif item.item_type == "action":
            raw_lbl = " Ejecutar "
            inner_w = len(raw_lbl)
            c_hov = (hover_sub == "control")
            c_top = self.theme_engine.style("accent" if c_hov else b_col, None, "┌" + ("─" * inner_w) + "┐", bold=c_hov)
            inner_bg = "accent" if c_hov else ("selection" if is_sel else None)
            inner_s = self.theme_engine.style("bright_foreground", inner_bg, raw_lbl, bold=True)
            c_mid = self.theme_engine.fg("accent" if c_hov else sh_col, "┃") + inner_s + self.theme_engine.fg(b_col, "│")
            c_bot = self.theme_engine.fg("accent" if c_hov else sh_col, "┗" + ("━" * inner_w) + "┙")
            return c_top, c_mid, c_bot, inner_w + 2

        elif item.item_type == "slider":
            pct = int(((val - item.min_val) / max(0.001, item.max_val - item.min_val)) * 10)
            pct = max(0, min(10, pct))
            bar = "─" * pct + "●" + "─" * (10 - pct)
            val_txt = f"{val:>5.2f}" if isinstance(val, float) else f"{str(val):>5}"
            raw_mid = f"{bar} {val_txt}"
            vis_w = len(raw_mid)
            s_hov = (hover_sub == "slider")
            c_top = " " * vis_w
            c_mid = self.theme_engine.style("accent" if s_hov else ("bright_foreground" if is_sel else "foreground"), None, raw_mid, bold=(is_sel or s_hov))
            c_bot = " " * vis_w
            return c_top, c_mid, c_bot, vis_w

        raw = str(val)
        return " " * len(raw), raw, " " * len(raw), len(raw)

    def _render_modal_overlay(self, cols: int, rows: int) -> List[str]:
        """
        Renderiza ventanas modales centradas para:
        - "confirm_section_change": aplicar/descartar cambios al cambiar de sección
        - "confirm_reset": confirmar restablecimiento a valores predeterminados
        - "input_autostart": agregar aplicación, servicio o comando en autostart.lua
        - "input_theme_hex": ingresar color hexadecimal personalizado para el tema Omarchy
        """
        self._modal_button_click_map.clear()
        self._modal_kind_click_range = (0, 0, 0)

        if self.modal_state in ("input_autostart", "input_theme_hex"):
            return self._render_input_modal(cols, rows)

        if self.modal_state == "confirm_section_change":
            title = " CAMBIOS SIN APLICAR "
            msg_1 = "Has modificado opciones en la seccion actual."
            msg_2 = "¿Deseas aplicar los cambios antes de cambiar de seccion?"
            modal_btns = [
                (0, " Descartar "),
                (1, " Cancelar "),
                (2, " Aplicar "),
            ]
        else:
            title = " RESTABLECER CONFIGURACION "
            msg_1 = "Se restauraran todos los ajustes a los valores por defecto."
            msg_2 = "¿Deseas continuar con el restablecimiento?"
            modal_btns = [
                (0, " Cancelar "),
                (1, " Confirmar "),
            ]

        mw = min(max(58, len(msg_2) + 6), cols - 4)
        inner_mw = mw - 2
        mh = 10
        start_x = max(2, (cols - mw) // 2)
        start_y = max(3, (rows - mh) // 2)

        overlay: List[str] = []

        top_line = "┌" + ("─" * inner_mw) + "┐"
        title_centered = title.center(inner_mw)[:inner_mw]
        sep_line = "├" + ("─" * inner_mw) + "┤"
        m1_line = msg_1.center(inner_mw)[:inner_mw]
        m2_line = msg_2.center(inner_mw)[:inner_mw]
        empty_line = " " * inner_mw
        bot_line = "┗" + ("━" * inner_mw) + "┙"

        overlay.append(f"\033[{start_y};{start_x}H" + self.theme_engine.style("bright_foreground", "background", top_line, bold=True))
        overlay.append(f"\033[{start_y + 1};{start_x}H" + self.theme_engine.style("bright_foreground", "accent", "┃" + title_centered + "│", bold=True))
        overlay.append(f"\033[{start_y + 2};{start_x}H" + self.theme_engine.style("muted", "background", sep_line))
        overlay.append(f"\033[{start_y + 3};{start_x}H" + self.theme_engine.style("bright_foreground", "background", "┃" + m1_line + "│", bold=True))
        overlay.append(f"\033[{start_y + 4};{start_x}H" + self.theme_engine.style("foreground", "background", "┃" + m2_line + "│"))
        overlay.append(f"\033[{start_y + 5};{start_x}H" + self.theme_engine.style("foreground", "background", "┃" + empty_line + "│"))

        gap = 2
        btns_total_w = sum(len(lbl) + 2 for _, lbl in modal_btns) + gap * (len(modal_btns) - 1)
        pad_left = max(1, (inner_mw - btns_total_w) // 2)
        pad_right = max(0, inner_mw - btns_total_w - pad_left)

        btn_y_top = start_y + 6
        self._modal_button_row_range = (btn_y_top, btn_y_top + 2)

        b_r0 = [self.theme_engine.style("foreground", "background", "┃" + (" " * pad_left))]
        b_r1 = [self.theme_engine.style("foreground", "background", "┃" + (" " * pad_left))]
        b_r2 = [self.theme_engine.style("foreground", "background", "┃" + (" " * pad_left))]

        cur_x = start_x + 1 + pad_left
        for b_idx, b_lbl in modal_btns:
            bw = len(b_lbl) + 2
            is_b_sel = (self.modal_selected_idx == b_idx)
            self._modal_button_click_map[b_idx] = (cur_x, cur_x + bw - 1)

            b_col = "bright_foreground" if is_b_sel else "foreground"
            sh_col = "accent" if is_b_sel else "muted"

            r0_s = self.theme_engine.style(b_col, "background", "┌" + ("─" * len(b_lbl)) + "┐", bold=is_b_sel)
            r1_s = (
                self.theme_engine.style(sh_col, "background", "┃", bold=True)
                + self.theme_engine.style("bright_foreground" if is_b_sel else "foreground", "selection" if is_b_sel else "background", b_lbl, bold=is_b_sel)
                + self.theme_engine.style(b_col, "background", "│", bold=is_b_sel)
            )
            r2_s = self.theme_engine.style(sh_col, "background", "┗" + ("━" * len(b_lbl)) + "┙", bold=True)

            sep_gap = self.theme_engine.style("foreground", "background", " " * gap) if b_idx < len(modal_btns) - 1 else ""
            b_r0.append(r0_s + sep_gap)
            b_r1.append(r1_s + sep_gap)
            b_r2.append(r2_s + sep_gap)
            cur_x += bw + gap

        b_r0.append(self.theme_engine.style("foreground", "background", (" " * pad_right) + "│"))
        b_r1.append(self.theme_engine.style("foreground", "background", (" " * pad_right) + "│"))
        b_r2.append(self.theme_engine.style("foreground", "background", (" " * pad_right) + "│"))

        overlay.append(f"\033[{btn_y_top};{start_x}H" + "".join(b_r0))
        overlay.append(f"\033[{btn_y_top + 1};{start_x}H" + "".join(b_r1))
        overlay.append(f"\033[{btn_y_top + 2};{start_x}H" + "".join(b_r2))
        overlay.append(f"\033[{start_y + 9};{start_x}H" + self.theme_engine.style("accent", "background", bot_line, bold=True))

        return overlay

    def _render_input_modal(self, cols: int, rows: int) -> List[str]:
        """Renderiza la ventana modal interactiva para entrada de texto (Autostart o Color Hex)."""
        is_autostart = (self.modal_state == "input_autostart")
        if is_autostart:
            title = " AGREGAR A AUTOSTART "
            kind_txt = (
                "Tipo (↑/↓ o clic):  ┌─────────────────────────────────────────┐"
            )
            kind_val = (
                "Aplicacion / Servicio (o.launch_on_start)"
                if self.modal_input_kind == "launch"
                else "Comando / Script      (o.exec_on_start)  "
            )
            prompt_lbl = "Escribe el comando, servicio o aplicacion:"
        else:
            title = " EDITAR COLOR HEX DEL TEMA OMARCHY "
            kind_txt = "Propiedad (↑/↓ o clic):"
            kind_val = f"Color a editar: {self.modal_hex_target} ▾"
            prompt_lbl = "Escribe el codigo hexadecimal (ej. #E31B23):"

        mw = min(64, cols - 4)
        inner_mw = mw - 2
        mh = 12
        start_x = max(2, (cols - mw) // 2)
        start_y = max(2, (rows - mh) // 2)

        overlay: List[str] = []
        top_line = "┌" + ("─" * inner_mw) + "┐"
        title_centered = title.center(inner_mw)[:inner_mw]
        sep_line = "├" + ("─" * inner_mw) + "┤"
        bot_line = "┗" + ("━" * inner_mw) + "┙"

        # Selector de tipo clicable en fila start_y + 3
        selector_line = f"  Tipo (↑/↓ o clic): {kind_val} ▾".ljust(inner_mw)[:inner_mw]
        self._modal_kind_click_range = (start_y + 3, start_x + 2, start_x + inner_mw - 2)

        # Campo de texto con cursor█
        box_w = inner_mw - 6
        shown_txt = (self.modal_input_text + "█")[-box_w:].ljust(box_w)
        input_top = ("  ┌" + ("─" * box_w) + "┐  ").ljust(inner_mw)[:inner_mw]
        input_mid = f"  ┃{shown_txt}│  ".ljust(inner_mw)[:inner_mw]
        input_bot = ("  ┗" + ("━" * box_w) + "┙  ").ljust(inner_mw)[:inner_mw]

        overlay.append(f"\033[{start_y};{start_x}H" + self.theme_engine.style("bright_foreground", "background", top_line, bold=True))
        overlay.append(f"\033[{start_y + 1};{start_x}H" + self.theme_engine.style("bright_foreground", "accent", "┃" + title_centered + "│", bold=True))
        overlay.append(f"\033[{start_y + 2};{start_x}H" + self.theme_engine.style("muted", "background", sep_line))
        overlay.append(f"\033[{start_y + 3};{start_x}H" + self.theme_engine.style("bright_foreground", "selection", "┃" + selector_line + "│", bold=True))
        overlay.append(f"\033[{start_y + 4};{start_x}H" + self.theme_engine.style("muted", "background", "┃" + f"  {prompt_lbl}".ljust(inner_mw)[:inner_mw] + "│"))
        overlay.append(f"\033[{start_y + 5};{start_x}H" + self.theme_engine.style("foreground", "background", "┃" + input_top + "│"))
        overlay.append(f"\033[{start_y + 6};{start_x}H" + self.theme_engine.style("bright_foreground", "background", "┃" + input_mid + "│", bold=True))
        overlay.append(f"\033[{start_y + 7};{start_x}H" + self.theme_engine.style("accent", "background", "┃" + input_bot + "│"))

        modal_btns = [
            (0, " Cancelar "),
            (1, " Agregar " if is_autostart else " Aplicar "),
        ]
        gap = 3
        btns_total_w = sum(len(lbl) + 2 for _, lbl in modal_btns) + gap
        pad_left = max(1, (inner_mw - btns_total_w) // 2)
        pad_right = max(0, inner_mw - btns_total_w - pad_left)

        btn_y_top = start_y + 8
        self._modal_button_row_range = (btn_y_top, btn_y_top + 2)

        b_r0 = [self.theme_engine.style("foreground", "background", "┃" + (" " * pad_left))]
        b_r1 = [self.theme_engine.style("foreground", "background", "┃" + (" " * pad_left))]
        b_r2 = [self.theme_engine.style("foreground", "background", "┃" + (" " * pad_left))]

        cur_x = start_x + 1 + pad_left
        for b_idx, b_lbl in modal_btns:
            bw = len(b_lbl) + 2
            is_b_sel = (self.modal_selected_idx == b_idx)
            self._modal_button_click_map[b_idx] = (cur_x, cur_x + bw - 1)
            b_col = "bright_foreground" if is_b_sel else "foreground"
            sh_col = "accent" if is_b_sel else "muted"

            r0_s = self.theme_engine.style(b_col, "background", "┌" + ("─" * len(b_lbl)) + "┐", bold=is_b_sel)
            r1_s = (
                self.theme_engine.style(sh_col, "background", "┃", bold=True)
                + self.theme_engine.style("bright_foreground" if is_b_sel else "foreground", "selection" if is_b_sel else "background", b_lbl, bold=is_b_sel)
                + self.theme_engine.style(b_col, "background", "│", bold=is_b_sel)
            )
            r2_s = self.theme_engine.style(sh_col, "background", "┗" + ("━" * len(b_lbl)) + "┙", bold=True)

            sep_gap = self.theme_engine.style("foreground", "background", " " * gap) if b_idx == 0 else ""
            b_r0.append(r0_s + sep_gap)
            b_r1.append(r1_s + sep_gap)
            b_r2.append(r2_s + sep_gap)
            cur_x += bw + gap

        b_r0.append(self.theme_engine.style("foreground", "background", (" " * pad_right) + "│"))
        b_r1.append(self.theme_engine.style("foreground", "background", (" " * pad_right) + "│"))
        b_r2.append(self.theme_engine.style("foreground", "background", (" " * pad_right) + "│"))

        overlay.append(f"\033[{btn_y_top};{start_x}H" + "".join(b_r0))
        overlay.append(f"\033[{btn_y_top + 1};{start_x}H" + "".join(b_r1))
        overlay.append(f"\033[{btn_y_top + 2};{start_x}H" + "".join(b_r2))
        overlay.append(f"\033[{start_y + 11};{start_x}H" + self.theme_engine.style("accent", "background", bot_line, bold=True))
        return overlay

    def _get_item_value(self, item: SectionItem) -> Any:
        """Obtiene el valor actual de la variable en memoria."""
        key = item.key

        if key.startswith("autostart:item:"):
            idx = int(key.split(":")[-1])
            if 0 <= idx < len(self.autostart_items):
                return bool(self.autostart_items[idx].get("enabled", False))
            return False

        key_defaults = {
            "general:gaps_in": ("gaps_in", 5),
            "general:gaps_out": ("gaps_out", 10),
            "general:border_size": ("border_size", 2),
            "general:resize_on_border": ("resize_on_border", True),
            "general:layout": ("layout", "dwindle"),
            "general:allow_tearing": ("allow_tearing", False),
            "general:snap:enabled": ("snap_enabled", False),
            "decoration:rounding": ("rounding", 0),
            "decoration:active_opacity": ("active_opacity", 1.0),
            "decoration:inactive_opacity": ("inactive_opacity", 0.95),
            "decoration:dim_inactive": ("dim_inactive", False),
            "decoration:dim_strength": ("dim_strength", 0.15),
            "decoration:blur:enabled": ("blur_enabled", True),
            "decoration:blur:size": ("blur_size", 5),
            "decoration:blur:passes": ("blur_passes", 2),
            "decoration:shadow:enabled": ("shadow_enabled", True),
            "animations:enabled": ("animations_enabled", True),
            "animations:preset": ("animation_preset", "smooth"),
            "animations:windows": ("anim_windows", "popin 80%"),
            "animations:workspaces": ("anim_workspaces", "slide"),
            "cursor:no_hardware_cursors": ("no_hw_cursors", False),
            "cursor:inactive_timeout": ("cursor_timeout", 0),
            "cursor:zoom_factor": ("cursor_zoom", 1.0),
            "input:repeat_rate": ("repeat_rate", 40),
            "input:repeat_delay": ("repeat_delay", 250),
            "input:numlock_by_default": ("numlock", True),
            "input:sensitivity": ("sensitivity", 0.0),
            "input:accel_profile": ("accel_profile", "flat"),
            "input:touchpad:natural_scroll": ("natural_scroll", False),
            "input:touchpad:clickfinger_behavior": ("clickfinger", True),
            "input:touchpad:tap-to-click": ("tap_to_click", True),
            "input:touchpad:disable_while_typing": ("disable_typing", True),
            "gestures:workspace_swipe": ("workspace_swipe", True),
            "workspace:count": ("workspace_count", 5),
            "workspace:layout_toggle": ("workspace_layout", "dwindle"),
            "dwindle:force_split": ("dwindle_force_split", 0),
            "dwindle:preserve_split": ("dwindle_preserve_split", True),
            "dwindle:smart_split": ("dwindle_smart_split", False),
            "master:new_status": ("master_new_status", "slave"),
            "rules:pavucontrol_float": ("rules_pavucontrol_float", True),
            "rules:calculator_float": ("rules_calculator_float", True),
            "omarchy:theme": ("omarchy_theme_name", self.theme_engine.current_theme),
            "omarchy:theme_mode": ("omarchy_theme_mode", self.theme_engine.mode),
            "omarchy:theme_accent": ("omarchy_theme_accent", "#E31B23"),
            "omarchy:theme_bg": ("omarchy_theme_bg", "#08080B"),
            "omarchy:theme_fg": ("omarchy_theme_fg", "#d8d8d8"),
            "omarchy:theme_sel": ("omarchy_theme_sel", "#45475a"),
            "omarchy:icons": ("omarchy_icons", self.theme_engine.icon_theme),
        }

        if key in key_defaults:
            s_key, def_val = key_defaults[key]
            return self.settings.get(s_key, def_val)

        if key == "input:compose_key":
            return "Alt Gr (Compose)" if self.settings.get("compose_key", "ralt") == "ralt" else "Bloq Mayús (Compose)"

        if key == "display:scale":
            return f"{self.monitors[0].get('scale', 1.0)}x" if self.monitors else "1x"
        if key == "display:mode":
            if "monitor_mode" in self.settings:
                return self.settings["monitor_mode"]
            if self.monitors:
                m = self.monitors[0]
                return f"{m.get('width')}x{m.get('height')}@{m.get('refreshRate', 60):.0f}Hz"
            return "1920x1080@60Hz"

        return self.settings.get(key, "-")

    def has_unsaved_changes(self) -> bool:
        """Indica si el usuario modificó algún ajuste o entrada de autostart respecto al último estado aplicado."""
        return (self.settings != self.saved_settings) or (self.autostart_items != self.saved_autostart)

    def _request_section_change(self, target_idx: int, focus_content: bool = False) -> None:
        """
        Cambia a la sección 'target_idx' de la barra lateral izquierda.
        Si existen cambios sin aplicar en la sección actual, abre la ventana modal de confirmación.
        """
        target_idx = max(0, min(len(self.SECTIONS) - 1, target_idx))
        if target_idx == self.current_section_idx:
            if focus_content:
                self.active_pane = "content"
            return

        if self.has_unsaved_changes():
            self.modal_state = "confirm_section_change"
            self.pending_section_idx = target_idx
            self.pending_focus_content = focus_content
            self.modal_selected_idx = 2  # Por defecto en 'Aplicar' (0: Descartar, 1: Cancelar, 2: Aplicar)
        else:
            self.current_section_idx = target_idx
            self.selected_item_idx = 0
            self.content_scroll_offset = 0
            if focus_content:
                self.active_pane = "content"

    def _execute_modal_choice(self, choice_idx: int) -> None:
        """Ejecuta la acción seleccionada dentro de la ventana modal activa."""
        state = self.modal_state
        self.modal_state = None

        if state == "confirm_section_change":
            if choice_idx == 0:  # Descartar cambios y cambiar de sección
                self.settings = dict(self.saved_settings)
                self.autostart_items = [dict(x) for x in self.saved_autostart]
                self.config_sync.save_gui_settings(self.settings, apply_live=True)
                self.config_sync.save_autostart_items(self.autostart_items)
                self.status_message = "Cambios descartados."
                if self.pending_section_idx is not None:
                    self.current_section_idx = self.pending_section_idx
                    self.selected_item_idx = 0
                    self.content_scroll_offset = 0
                    if self.pending_focus_content:
                        self.active_pane = "content"
            elif choice_idx == 1:  # Cancelar (permanecer en la sección actual)
                self.status_message = "Cambio de seccion cancelado."
            elif choice_idx == 2:  # Aplicar cambios y cambiar de sección
                self.save_all()
                if self.pending_section_idx is not None:
                    self.current_section_idx = self.pending_section_idx
                    self.selected_item_idx = 0
                    self.content_scroll_offset = 0
                    if self.pending_focus_content:
                        self.active_pane = "content"
            self.pending_section_idx = None

        elif state == "confirm_reset":
            if choice_idx == 0:  # Cancelar
                self.status_message = "Restablecimiento cancelado."
            elif choice_idx == 1:  # Confirmar restablecimiento
                self._perform_reset_to_defaults()

        elif state == "input_autostart":
            if choice_idx == 1:
                cmd_clean = self.modal_input_text.strip()
                if cmd_clean:
                    self.autostart_items.append({
                        "cmd": cmd_clean,
                        "kind": self.modal_input_kind,
                        "enabled": True,
                    })
                    self._sync_autostart_into_settings()
                    self.config_sync.save_autostart_items(self.autostart_items)
                    self.saved_autostart = [dict(x) for x in self.autostart_items]
                    self.saved_settings = dict(self.settings)
                    self.section_items["autostart"] = self._build_autostart_section_items()
                    self.status_message = f"✓ Agregado a autostart.lua: {cmd_clean}"
                else:
                    self.status_message = "Entrada vacia cancelada."
            else:
                self.status_message = "Agregar a autostart cancelado."
            self.modal_input_text = ""

        elif state == "input_theme_hex":
            if choice_idx == 1:
                hex_val = self.modal_input_text.strip()
                if not hex_val.startswith("#"):
                    hex_val = "#" + hex_val
                if re.match(r"^#[0-9A-Fa-f]{6}$", hex_val):
                    target_map = {
                        "accent": "omarchy:theme_accent",
                        "background": "omarchy:theme_bg",
                        "foreground": "omarchy:theme_fg",
                        "selection": "omarchy:theme_sel",
                    }
                    item_key = target_map.get(self.modal_hex_target, "omarchy:theme_accent")
                    self._set_item_value(item_key, hex_val)
                    self.save_all()
                    self.status_message = f"✓ Color {self.modal_hex_target} actualizado a {hex_val} en tema actual y original."
                else:
                    self.status_message = "Formato Hex invalido (usa #RRGGBB, ej. #E31B23)."
            self.modal_input_text = ""

    # ==========================
    # MANEJO DE ENTRADA Y RATÓN
    # ==========================

    def handle_input(self, fd: int) -> None:
        r, _, _ = select.select([fd], [], [], 0.05)
        if not r:
            return

        ch = os.read(fd, 4096)
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

        # Al usar el teclado limpiamos los estados visuales de hover del ratón
        self.hover_sidebar_idx = None
        self.hover_item_idx = None
        self.hover_subcontrol = None
        self.hover_button_key = None

        # Si hay una ventana modal de entrada de texto activa (input_autostart o input_theme_hex)
        if self.modal_state in ("input_autostart", "input_theme_hex"):
            if ch == b"\x1b" and len(ch) == 1:
                self.modal_state = None
                self.modal_input_text = ""
                return
            if ch in (b"\x1b[A", b"\x1b[B"):  # Arriba / Abajo cambia el tipo/propiedad
                self._cycle_input_modal_kind()
                return
            if ch in (b"\x1b[D", b"\x1b[Z"):
                self.modal_selected_idx = max(0, self.modal_selected_idx - 1)
                return
            if ch in (b"\x1b[C", b"\t"):
                self.modal_selected_idx = min(1, self.modal_selected_idx + 1)
                return
            if ch in (b"\r", b"\n"):
                self._execute_modal_choice(self.modal_selected_idx)
                return
            if ch in (b"\x7f", b"\x08"):  # Backspace
                self.modal_input_text = self.modal_input_text[:-1]
                return
            # Caracteres imprimibles
            try:
                decoded = ch.decode("utf-8", errors="ignore")
                for c in decoded:
                    if c.isprintable() and c not in ("\r", "\n", "\t"):
                        self.modal_input_text += c
            except Exception:
                pass
            return

        # Si hay una ventana modal de confirmación activa
        if self.modal_state:
            max_idx = 2 if self.modal_state == "confirm_section_change" else 1
            if ch == b"\x1b" and len(ch) == 1:
                self.modal_state = None
                self.pending_section_idx = None
                return
            if ch in (b"\x1b[D", b"\x1b[Z"):  # Izquierda / Shift+Tab
                self.modal_selected_idx = max(0, self.modal_selected_idx - 1)
                return
            if ch in (b"\x1b[C", b"\t"):  # Derecha / Tab
                self.modal_selected_idx = min(max_idx, self.modal_selected_idx + 1)
                return
            if ch in (b"\r", b"\n", b" "):
                self._execute_modal_choice(self.modal_selected_idx)
                return
            return

        # Salir con q o Esc
        if ch in (b"q", b"Q", b"\x1b") and len(ch) == 1:
            self.running = False
            return

        # Eliminar entrada de autostart con Supr / Delete (\x1b[3~) o 'x'
        if ch in (b"\x1b[3~", b"x", b"X"):
            sec_id = self.SECTIONS[self.current_section_idx][1]
            if sec_id == "autostart" and self.selected_item_idx >= 1:
                entry_idx = self.selected_item_idx - 1
                if 0 <= entry_idx < len(self.autostart_items):
                    removed = self.autostart_items.pop(entry_idx)
                    self._sync_autostart_into_settings()
                    self.section_items["autostart"] = self._build_autostart_section_items()
                    self.selected_item_idx = max(0, min(self.selected_item_idx, len(self.section_items["autostart"]) - 1))
                    self.status_message = f"Entrada eliminada: {removed.get('cmd')} (Pulsa Aplicar para guardar)"
            return

        # Atajos rápidos físicos directos (a/s: Aplicar, c: Cancelar, r: Restablecer)
        if ch in (b"a", b"A", b"s", b"S"):
            self.save_all()
            return
        if ch in (b"c", b"C"):
            self.cancel_changes()
            return
        if ch in (b"r", b"R"):
            self.reset_to_defaults()
            return

        # Cambiar foco con Tab
        if ch in (b"\t", b"\x1b[Z"):
            if self.active_pane == "sidebar":
                self.active_pane = "content"
            elif self.active_pane == "content":
                self.active_pane = "buttons"
            else:
                self.active_pane = "sidebar"
            return

        # Navegación izquierda/derecha
        if ch == b"\x1b[D":  # Flecha Izquierda
            if self.active_pane == "buttons":
                self.selected_button_idx = max(0, self.selected_button_idx - 1)
            elif self.active_pane == "content":
                self._adjust_current_item(delta=-1)
            else:
                self.active_pane = "sidebar"
            return

        if ch == b"\x1b[C":  # Flecha Derecha
            if self.active_pane == "buttons":
                self.selected_button_idx = min(2, self.selected_button_idx + 1)
            elif self.active_pane == "content":
                self._adjust_current_item(delta=1)
            else:
                self.active_pane = "content"
            return

        # Navegación vertical arriba/abajo
        if ch == b"\x1b[A":  # Flecha Arriba
            if self.active_pane == "buttons":
                self.active_pane = "content"
            elif self.active_pane == "sidebar":
                self._request_section_change(self.current_section_idx - 1, focus_content=False)
            else:
                self.selected_item_idx = max(0, self.selected_item_idx - 1)
            return

        if ch == b"\x1b[B":  # Flecha Abajo
            if self.active_pane == "sidebar":
                self._request_section_change(self.current_section_idx + 1, focus_content=False)
            elif self.active_pane == "content":
                sec_id = self.SECTIONS[self.current_section_idx][1]
                items_len = len(self.section_items.get(sec_id, []))
                if self.selected_item_idx >= items_len - 1:
                    self.active_pane = "buttons"
                    self.selected_button_idx = 2
                else:
                    self.selected_item_idx += 1
            return

        # Enter o Espacio para activar/conmutar
        if ch in (b"\r", b"\n", b" "):
            if self.active_pane == "sidebar":
                self.active_pane = "content"
            elif self.active_pane == "buttons":
                if self.selected_button_idx == 0:
                    self.reset_to_defaults()
                elif self.selected_button_idx == 1:
                    self.cancel_changes()
                elif self.selected_button_idx == 2:
                    self.save_all()
            else:
                self._activate_current_item()
            return

    def _cycle_input_modal_kind(self) -> None:
        """Alterna el selector de tipo en los modales de entrada de texto."""
        if self.modal_state == "input_autostart":
            self.modal_input_kind = "exec" if self.modal_input_kind == "launch" else "launch"
        elif self.modal_state == "input_theme_hex":
            order = ["accent", "background", "foreground", "selection"]
            idx = (order.index(self.modal_hex_target) + 1) % len(order) if self.modal_hex_target in order else 0
            self.modal_hex_target = order[idx]
            cur_map = {
                "accent": self.settings.get("omarchy_theme_accent", "#E31B23"),
                "background": self.settings.get("omarchy_theme_bg", "#08080B"),
                "foreground": self.settings.get("omarchy_theme_fg", "#d8d8d8"),
                "selection": self.settings.get("omarchy_theme_sel", "#45475a"),
            }
            self.modal_input_text = cur_map.get(self.modal_hex_target, "#E31B23")

    def _handle_mouse_event(self, btn: int, x: int, y: int, act: bytes) -> None:
        """Procesa clics, arrastres, rueda del ratón y movimiento hover (btn == 35)."""
        cols, rows = shutil.get_terminal_size((90, 26))
        sidebar_w = 26

        # Si hay una ventana modal abierta, dirigir clics y hover al modal
        if self.modal_state:
            if act == b"M" and btn == 35:
                m_ymin, m_ymax = self._modal_button_row_range
                self.hover_modal_btn_idx = None
                if m_ymin <= y <= m_ymax:
                    for b_idx, (bx_min, bx_max) in self._modal_button_click_map.items():
                        if bx_min <= x <= bx_max:
                            self.modal_selected_idx = b_idx
                            self.hover_modal_btn_idx = b_idx
                            return
                return

            if act == b"M" and btn == 0:
                ky, kxmin, kxmax = self._modal_kind_click_range
                if y == ky and kxmin <= x <= kxmax:
                    self._cycle_input_modal_kind()
                    return
                m_ymin, m_ymax = self._modal_button_row_range
                if m_ymin <= y <= m_ymax:
                    for b_idx, (bx_min, bx_max) in self._modal_button_click_map.items():
                        if bx_min <= x <= bx_max:
                            self.modal_selected_idx = b_idx
                            self._execute_modal_choice(b_idx)
                            return
            return

        if act == b"M":
            # 0. Movimiento de cursor sin clic (Hover: btn == 35)
            if btn == 35:
                btn_y_min, btn_y_max = self._button_row_range

                # Hover sobre barra lateral izquierda
                if x <= sidebar_w:
                    sec_idx = self._sidebar_click_map.get(y)
                    self.hover_sidebar_idx = sec_idx
                    self.hover_item_idx = None
                    self.hover_subcontrol = None
                    self.hover_button_key = None
                    if sec_idx is not None:
                        _, _, _, s_title, s_desc = self.SECTIONS[sec_idx]
                        self.status_message = f"{s_title}: {s_desc}"
                    return

                # Hover sobre los 3 botones inferiores 3D
                if x > sidebar_w + 1 and btn_y_min <= y <= btn_y_max:
                    self.hover_sidebar_idx = None
                    self.hover_item_idx = None
                    self.hover_subcontrol = None
                    hovered_btn = None
                    btn_idx_map = {"reset": 0, "cancel": 1, "save": 2}
                    for b_key, (bx_min, bx_max) in self._button_click_map.items():
                        if bx_min <= x <= bx_max:
                            hovered_btn = b_key
                            self.active_pane = "buttons"
                            self.selected_button_idx = btn_idx_map[b_key]
                            break
                    self.hover_button_key = hovered_btn
                    return

                # Hover sobre los elementos y controles del panel derecho
                if x > sidebar_w + 1:
                    info = self._content_click_map.get(y)
                    if info:
                        self.hover_sidebar_idx = None
                        self.hover_button_key = None
                        self.hover_item_idx = info["item_idx"]
                        self.active_pane = "content"
                        self.selected_item_idx = info["item_idx"]
                        item = info["item"]
                        self.status_message = f"{item.name}: {item.desc}"

                        if item.item_type == "stepper":
                            m_start, m_end = info["minus_range"]
                            p_start, p_end = info["plus_range"]
                            if m_start <= x <= m_end:
                                self.hover_subcontrol = "minus"
                            elif p_start <= x <= p_end:
                                self.hover_subcontrol = "plus"
                            else:
                                self.hover_subcontrol = None
                        elif item.item_type in ("toggle", "select", "action"):
                            c_start, c_end = info["control_range"]
                            self.hover_subcontrol = "control" if (c_start <= x <= c_end) else None
                        elif item.item_type == "slider":
                            s_start, s_end = info["slider_range"]
                            self.hover_subcontrol = "slider" if (s_start <= x <= s_end) else None
                        else:
                            self.hover_subcontrol = None
                        return

                # Fuera de elementos interactivos
                self.hover_sidebar_idx = None
                self.hover_item_idx = None
                self.hover_subcontrol = None
                self.hover_button_key = None
                return

            # 1. Clic Izquierdo (btn == 0)
            if btn == 0:
                # Clic en barra de título superior
                if y == 1:
                    if x >= cols - 12:
                        self.running = False
                    return

                # Clic en la zona de los 3 botones inferiores (3 filas de alto en el panel derecho)
                btn_y_min, btn_y_max = self._button_row_range
                if x > sidebar_w + 1 and btn_y_min <= y <= btn_y_max:
                    reset_r = self._button_click_map.get("reset")
                    cancel_r = self._button_click_map.get("cancel")
                    save_r = self._button_click_map.get("save")

                    if reset_r and reset_r[0] <= x <= reset_r[1]:
                        self.active_pane = "buttons"
                        self.selected_button_idx = 0
                        self.reset_to_defaults()
                        return
                    elif cancel_r and cancel_r[0] <= x <= cancel_r[1]:
                        self.active_pane = "buttons"
                        self.selected_button_idx = 1
                        self.cancel_changes()
                        return
                    elif save_r and save_r[0] <= x <= save_r[1]:
                        self.active_pane = "buttons"
                        self.selected_button_idx = 2
                        self.save_all()
                        return

                # Clic en barra inferior de estado (rows)
                if y == rows:
                    if x > cols - 12:
                        self.running = False
                    elif x <= 16:
                        if self.active_pane == "sidebar":
                            self.active_pane = "content"
                        elif self.active_pane == "content":
                            self.active_pane = "buttons"
                        else:
                            self.active_pane = "sidebar"
                    return

                # Clic en barra lateral izquierda (Sidebar) -> verifica cambios sin aplicar antes de cambiar
                if x <= sidebar_w:
                    sec_idx = self._sidebar_click_map.get(y)
                    if sec_idx is not None:
                        self._request_section_change(sec_idx, focus_content=True)
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
                    self._request_section_change(self.current_section_idx - 1, focus_content=False)
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
                    self._request_section_change(self.current_section_idx + 1, focus_content=False)
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
        if key.startswith("autostart:item:"):
            idx = int(key.split(":")[-1])
            if 0 <= idx < len(self.autostart_items):
                self.autostart_items[idx]["enabled"] = bool(val)
                self._sync_autostart_into_settings()
            return

        key_map = {
            "general:gaps_in": ("gaps_in", int),
            "general:gaps_out": ("gaps_out", int),
            "general:border_size": ("border_size", int),
            "general:resize_on_border": ("resize_on_border", bool),
            "general:layout": ("layout", str),
            "general:allow_tearing": ("allow_tearing", bool),
            "general:snap:enabled": ("snap_enabled", bool),
            "decoration:rounding": ("rounding", int),
            "decoration:active_opacity": ("active_opacity", float),
            "decoration:inactive_opacity": ("inactive_opacity", float),
            "decoration:dim_inactive": ("dim_inactive", bool),
            "decoration:dim_strength": ("dim_strength", float),
            "decoration:blur:enabled": ("blur_enabled", bool),
            "decoration:blur:size": ("blur_size", int),
            "decoration:blur:passes": ("blur_passes", int),
            "decoration:shadow:enabled": ("shadow_enabled", bool),
            "animations:enabled": ("animations_enabled", bool),
            "animations:preset": ("animation_preset", str),
            "animations:windows": ("anim_windows", str),
            "animations:workspaces": ("anim_workspaces", str),
            "cursor:no_hardware_cursors": ("no_hw_cursors", bool),
            "cursor:inactive_timeout": ("cursor_timeout", int),
            "cursor:zoom_factor": ("cursor_zoom", float),
            "input:repeat_rate": ("repeat_rate", int),
            "input:repeat_delay": ("repeat_delay", int),
            "input:numlock_by_default": ("numlock", bool),
            "input:sensitivity": ("sensitivity", float),
            "input:accel_profile": ("accel_profile", str),
            "input:touchpad:natural_scroll": ("natural_scroll", bool),
            "input:touchpad:clickfinger_behavior": ("clickfinger", bool),
            "input:touchpad:tap-to-click": ("tap_to_click", bool),
            "input:touchpad:disable_while_typing": ("disable_typing", bool),
            "gestures:workspace_swipe": ("workspace_swipe", bool),
            "workspace:count": ("workspace_count", int),
            "workspace:layout_toggle": ("workspace_layout", str),
            "dwindle:force_split": ("dwindle_force_split", int),
            "dwindle:preserve_split": ("dwindle_preserve_split", bool),
            "dwindle:smart_split": ("dwindle_smart_split", bool),
            "master:new_status": ("master_new_status", str),
            "rules:pavucontrol_float": ("rules_pavucontrol_float", bool),
            "rules:calculator_float": ("rules_calculator_float", bool),
            "omarchy:theme_mode": ("omarchy_theme_mode", str),
            "omarchy:theme_accent": ("omarchy_theme_accent", str),
            "omarchy:theme_bg": ("omarchy_theme_bg", str),
            "omarchy:theme_fg": ("omarchy_theme_fg", str),
            "omarchy:theme_sel": ("omarchy_theme_sel", str),
            "omarchy:icons": ("omarchy_icons", str),
        }

        if key in key_map:
            s_key, caster = key_map[key]
            self.settings[s_key] = caster(val)
            # Previsualizar en vivo el cambio de color en el motor TUI
            if key == "omarchy:theme_accent":
                self.theme_engine._colors["accent"] = str(val)
            elif key == "omarchy:theme_bg":
                self.theme_engine._colors["background"] = str(val)
            elif key == "omarchy:theme_fg":
                self.theme_engine._colors["foreground"] = str(val)
                self.theme_engine._colors["bright_foreground"] = str(val)
            elif key == "omarchy:theme_sel":
                self.theme_engine._colors["selection"] = str(val)
        elif key == "input:compose_key":
            self.settings["compose_key"] = "ralt" if "Alt Gr" in str(val) else "caps"
        elif key == "display:scale":
            if self.monitors:
                scale_float = float(str(val).replace("x", ""))
                self.monitors[0]["scale"] = scale_float
                self.settings["monitor_scale"] = scale_float
        elif key == "display:mode":
            self.settings["monitor_mode"] = str(val)
        elif key == "omarchy:theme":
            self.status_message = f"Aplicando tema {val}..."
            self.render()
            self.theme_engine.set_theme(str(val))
            self._sync_theme_into_settings()
            self.saved_settings.update({
                "omarchy_theme_name": self.settings["omarchy_theme_name"],
                "omarchy_theme_mode": self.settings["omarchy_theme_mode"],
                "omarchy_theme_accent": self.settings["omarchy_theme_accent"],
                "omarchy_theme_bg": self.settings["omarchy_theme_bg"],
                "omarchy_theme_fg": self.settings["omarchy_theme_fg"],
                "omarchy_theme_sel": self.settings["omarchy_theme_sel"],
                "omarchy_icons": self.settings["omarchy_icons"],
            })
            self.section_items = self._init_section_items()
            self.status_message = f"✓ Tema {val} activado."
        else:
            self.settings[key] = val

    def _apply_hyprctl_live(self, key: str, val: Any) -> None:
        """Aplica la variable en caliente a Hyprland si corresponde."""
        hypr_map = {
            "general:gaps_in": "general:gaps_in",
            "general:gaps_out": "general:gaps_out",
            "general:border_size": "general:border_size",
            "general:resize_on_border": "general:resize_on_border",
            "general:layout": "general:layout",
            "general:allow_tearing": "general:allow_tearing",
            "general:snap:enabled": "general:snap:enabled",
            "decoration:rounding": "decoration:rounding",
            "decoration:active_opacity": "decoration:active_opacity",
            "decoration:inactive_opacity": "decoration:inactive_opacity",
            "decoration:dim_inactive": "decoration:dim_inactive",
            "decoration:dim_strength": "decoration:dim_strength",
            "decoration:blur:enabled": "decoration:blur:enabled",
            "decoration:blur:size": "decoration:blur:size",
            "decoration:blur:passes": "decoration:blur:passes",
            "decoration:shadow:enabled": "decoration:shadow:enabled",
            "animations:enabled": "animations:enabled",
            "cursor:no_hardware_cursors": "cursor:no_hardware_cursors",
            "cursor:inactive_timeout": "cursor:inactive_timeout",
            "cursor:zoom_factor": "cursor:zoom_factor",
            "input:repeat_rate": "input:repeat_rate",
            "input:repeat_delay": "input:repeat_delay",
            "input:numlock_by_default": "input:numlock_by_default",
            "input:sensitivity": "input:sensitivity",
            "input:accel_profile": "input:accel_profile",
            "input:touchpad:natural_scroll": "input:touchpad:natural_scroll",
            "input:touchpad:clickfinger_behavior": "input:touchpad:clickfinger_behavior",
            "input:touchpad:tap-to-click": "input:touchpad:tap-to-click",
            "input:touchpad:disable_while_typing": "input:touchpad:disable_while_typing",
            "dwindle:force_split": "dwindle:force_split",
            "dwindle:preserve_split": "dwindle:preserve_split",
            "dwindle:smart_split": "dwindle:smart_split",
            "master:new_status": "master:new_status",
        }
        if key in hypr_map:
            HyprIPC.set_keyword(hypr_map[key], val)

    def _execute_action(self, action_key: str) -> None:
        """Ejecuta acciones especiales como modales de autostart, edición de tema Omarchy o utilidades."""
        if action_key == "action:add_autostart":
            self.modal_state = "input_autostart"
            self.modal_input_text = ""
            self.modal_input_kind = "launch"
            self.modal_selected_idx = 1
            return

        elif action_key == "action:custom_theme_hex":
            self.modal_state = "input_theme_hex"
            self.modal_hex_target = "accent"
            self.modal_input_text = str(self.settings.get("omarchy_theme_accent", "#E31B23"))
            self.modal_selected_idx = 1
            return

        elif action_key == "action:next_wallpaper":
            try:
                subprocess.run(["omarchy-theme-bg-next"], capture_output=True, timeout=5)
                self.status_message = "✓ Fondo de pantalla cambiado al siguiente del tema."
            except Exception:
                self.status_message = "No se pudo ejecutar omarchy-theme-bg-next."

        elif action_key == "action:toggle_bar":
            try:
                subprocess.run(["omarchy-toggle-bar"], capture_output=True, timeout=5)
                self.status_message = "✓ Barra superior de Omarchy conmutada."
            except Exception:
                self.status_message = "No se pudo conmutar la barra superior."

        elif action_key == "action:toggle_nightlight":
            try:
                subprocess.run(["omarchy-toggle-nightlight"], capture_output=True, timeout=5)
                self.status_message = "✓ Modo de luz nocturna conmutado."
            except Exception:
                self.status_message = "No se pudo conmutar la luz nocturna."

        elif action_key == "action:fix_caps":
            use_ralt = (self.settings.get("compose_key", "ralt") == "ralt")
            self.config_sync.fix_caps_lock(use_ralt=use_ralt)
            self.saved_settings["compose_key"] = self.settings.get("compose_key", "ralt")
            self.status_message = "✓ Tecla Bloq Mayús configurada en input.lua."

        elif action_key == "action:save_monitor":
            if self.monitors:
                m = self.monitors[0]
                mode_cfg = self.settings.get("monitor_mode", f"{m.get('width')}x{m.get('height')}@{m.get('refreshRate', 60):.0f}Hz")
                if "@" in mode_cfg:
                    res_part, hz_part = mode_cfg.split("@", 1)
                    hz = float(hz_part.lower().replace("hz", "") or 60.0)
                else:
                    res_part = f"{m.get('width')}x{m.get('height')}"
                    hz = float(m.get("refreshRate", 60.0))
                scale = float(m.get("scale", 1.0))
                ok = self.config_sync.save_monitor_config(m.get("name"), res_part, hz, scale)
                if ok:
                    self.saved_settings["monitor_scale"] = self.settings.get("monitor_scale", scale)
                    self.saved_settings["monitor_mode"] = self.settings.get("monitor_mode", mode_cfg)
                    self.status_message = "✓ Configuración de monitor aplicada en monitors.lua."
                else:
                    self.status_message = "Error al guardar monitor."

        elif action_key == "action:apply_lizarbe_full":
            self.status_message = "Aplicando Setup Lizarbe..."
            self.render()
            LizarbeManager.apply_lizarbe_theme("lizarbe")
            LizarbeManager.ensure_fastfetch_logo()
            self.config_sync.fix_caps_lock(use_ralt=True)
            self.install_update_hook()
            self.theme_engine.reload()
            self._sync_theme_into_settings()
            self.saved_settings = dict(self.settings)
            self.status_message = "✓ Setup Lizarbe aplicado correctamente."

        elif action_key == "action:install_hook":
            self.install_update_hook()

    def _has_theme_edits(self) -> bool:
        """Verifica si se editaron propiedades del tema Omarchy activo."""
        theme_keys = (
            "omarchy_theme_mode",
            "omarchy_theme_accent",
            "omarchy_theme_bg",
            "omarchy_theme_fg",
            "omarchy_theme_sel",
            "omarchy_icons",
        )
        return any(self.settings.get(k) != self.saved_settings.get(k) for k in theme_keys)

    def save_all(self) -> None:
        """Aplica y guarda todas las opciones en hyprland-gui.lua, autostart.lua y tema Omarchy."""
        ok_gui = self.config_sync.save_gui_settings(self.settings, apply_live=True)
        ok_auto = self.config_sync.save_autostart_items(self.autostart_items)

        # Si se cambió compose_key, persistir en input.lua
        if self.settings.get("compose_key") != self.saved_settings.get("compose_key"):
            self.config_sync.fix_caps_lock(use_ralt=(self.settings.get("compose_key", "ralt") == "ralt"))

        # Si se editó el tema Omarchy, persistir tanto en el tema activo como en el original
        if self._has_theme_edits():
            self.status_message = "Actualizando tema Omarchy activo y original..."
            self.render()
            theme_updates = {
                "mode": str(self.settings.get("omarchy_theme_mode", self.theme_engine.mode)),
                "accent": str(self.settings.get("omarchy_theme_accent", "#E31B23")),
                "background": str(self.settings.get("omarchy_theme_bg", "#08080B")),
                "foreground": str(self.settings.get("omarchy_theme_fg", "#d8d8d8")),
                "bright_foreground": str(self.settings.get("omarchy_theme_fg", "#d8d8d8")),
                "selection": str(self.settings.get("omarchy_theme_sel", "#45475a")),
            }
            self.theme_engine.save_theme_edits(
                theme_name=self.theme_engine.current_theme,
                updates=theme_updates,
                icon_theme=str(self.settings.get("omarchy_icons", self.theme_engine.icon_theme)),
                refresh_live=True,
            )
            self._sync_theme_into_settings()

        if ok_gui and ok_auto:
            self.saved_settings = dict(self.settings)
            self.saved_autostart = [dict(x) for x in self.autostart_items]
            self.status_message = "✓ Cambios aplicados en Hyprland y Omarchy."
        else:
            self.status_message = "Error al aplicar la configuracion."

    def cancel_changes(self) -> None:
        """Revierte cualquier cambio sin aplicar y cierra la ventana de la aplicación."""
        if self.has_unsaved_changes():
            self.settings = dict(self.saved_settings)
            self.autostart_items = [dict(x) for x in self.saved_autostart]
            self.config_sync.save_gui_settings(self.settings, apply_live=True)
            self.config_sync.save_autostart_items(self.autostart_items)
        self.running = False

    def reset_to_defaults(self) -> None:
        """Abre la ventana de confirmación antes de restablecer los ajustes a valores por defecto."""
        self.modal_state = "confirm_reset"
        self.modal_selected_idx = 1  # Por defecto en 'Confirmar' (0: Cancelar, 1: Confirmar)

    def _perform_reset_to_defaults(self) -> None:
        """Ejecuta el restablecimiento real tras la confirmación del usuario."""
        defaults = {
            "gaps_in": 5,
            "gaps_out": 10,
            "border_size": 2,
            "resize_on_border": True,
            "rounding": 0,
            "dim_inactive": False,
            "dim_strength": 0.15,
            "active_opacity": 1.0,
            "inactive_opacity": 0.95,
            "blur_enabled": True,
            "blur_size": 5,
            "blur_passes": 2,
            "shadow_enabled": True,
            "animations_enabled": True,
            "animation_preset": "smooth",
            "no_hw_cursors": False,
            "cursor_timeout": 0,
            "cursor_zoom": 1.0,
            "sensitivity": 0.0,
            "accel_profile": "flat",
            "natural_scroll": False,
            "layout": "dwindle",
            "compose_key": "ralt",
            "snap_enabled": False,
        }
        self.settings.update(defaults)
        self.config_sync.save_gui_settings(self.settings, apply_live=True)
        self.saved_settings = dict(self.settings)
        self.status_message = "✓ Ajustes restablecidos a los valores predeterminados de Omarchy."

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
