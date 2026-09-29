"""
Interfaz TUI Monolítica para Meca HyprConfig (Estilo HyprMod / GNOME / macOS).
Arquitectura de 2 paneles (Categorías a la izquierda, Variables de Hyprland y Omarchy a la derecha),
con soporte completo de ratón, menús desplegables, tarjetas de temas, controles en cuadrados cerrados,
modales interactivos, gestión de Autostart, Barra Superior y edición de temas de Omarchy.
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
    """Representa una variable, encabezado o tarjeta configurable dentro de una sección."""
    def __init__(
        self,
        key: str,
        name: str,
        desc: str,
        item_type: str,  # "stepper", "toggle", "select", "slider", "action", "header", "theme_card"
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
        ("LOOK & FEEL", "general", "", "General", "Gaps, bordes, snap magnético y layout principal"),
        ("LOOK & FEEL", "decoration", "", "Decoration", "Redondeo, opacidad, desenfoque Kawase y sombras"),
        ("LOOK & FEEL", "animations", "", "Animations", "Curvas bezier, velocidad y estilo de transiciones"),
        ("LOOK & FEEL", "cursor", "󰍽", "Cursor", "Tamaño, cursor por hardware, ocultación y zoom"),
        ("INPUT", "keybinds", "", "Keybinds", "Distribución de teclado, Bloq Mayús, repetición y atajos"),
        ("INPUT", "devices", "󰍽", "Devices", "Ratón, foco, touchpad y gestos de 3 dedos"),
        ("DISPLAY", "monitors", "󰍹", "Monitors", "Escala HiDPI, resolución, rotación, VRR y XWayland"),
        ("DISPLAY", "workspaces", "󰕰", "Workspaces", "Escritorios persistentes, layout y opciones misc"),
        ("WINDOW MANAGEMENT", "layouts", "󰕮", "Layouts", "Opciones detalladas de Dwindle, Master, Scrolling y Groupbar"),
        ("WINDOW MANAGEMENT", "rules", "", "Window Rules", "Reglas de ventanas flotantes, PiP, Steam y opacidad"),
        ("STARTUP & EXTRAS", "autostart", "", "Autostart", "Aplicaciones, servicios o comandos al iniciar sesión"),
        ("STARTUP & EXTRAS", "bar", "󰍜", "Barra Superior", "Posición, transparencia, reloj y widgets de la barra Omarchy"),
        ("STARTUP & EXTRAS", "themes", "󰏘", "Temas Omarchy", "Crear nuevos temas Omarchy y gestionar los ya creados"),
        ("STARTUP & EXTRAS", "omarchy", "󰚰", "Omarchy", "Fondos, luz nocturna, Setup Lizarbe y utilidades del sistema"),
    ]

    def __init__(self):
        self.theme_engine = ThemeEngine()
        self.config_sync = ConfigSync()
        self.running = True
        self._frame_count = 0

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
        self.installed_apps = self.config_sync.list_installed_applications()

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

        # Estado del menú desplegable (dropdown) para controles de tipo "select"
        self.dropdown_open: bool = False
        self.dropdown_item: Optional[SectionItem] = None
        self.dropdown_options: List[str] = []
        self.dropdown_idx: int = 0
        self.dropdown_scroll: int = 0
        self.hover_dropdown_idx: Optional[int] = None
        self.dropdown_anchor_y: int = 6
        self.dropdown_anchor_x: int = 40
        self._dropdown_row_map: Dict[int, int] = {}
        self._dropdown_box_bounds: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (y1, y2, x1, x2)

        # Estado de ventana modal:
        # None | "confirm_section_change" | "confirm_reset" | "input_autostart" | "input_theme_hex" | "create_theme"
        self.modal_state: Optional[str] = None
        self.modal_selected_idx: int = 0
        self.pending_section_idx: Optional[int] = None
        self.pending_focus_content: bool = False
        self._modal_button_click_map: Dict[int, Tuple[int, int]] = {}
        self._modal_button_row_range: Tuple[int, int] = (0, 0)

        # Estado de entrada de texto y selectores para modales interactivos
        self.modal_input_text: str = ""
        self.modal_input_kind: str = "launch"  # "launch" (App/Servicio) | "exec" (Comando)
        self.modal_hex_target: str = "accent"  # "accent" | "background" | "foreground" | "selection"
        self.modal_base_theme: str = self.theme_engine.current_theme
        self.modal_theme_mode: str = "dark"
        self._modal_kind_click_range: Tuple[int, int, int] = (0, 0, 0)  # (y, x_min, x_max)
        self._modal_mode_click_range: Tuple[int, int, int] = (0, 0, 0)  # (y, x_min, x_max)

        # Estado del selector desplegable de aplicaciones en Autostart
        self.autostart_dropdown_open: bool = False
        self.autostart_selected_app_name: str = ""
        self.autostart_app_idx: int = 0
        self.autostart_app_scroll: int = 0
        self.hover_autostart_app_idx: Optional[int] = None
        self._autostart_dropdown_btn_range: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (y1, y2, x1, x2)
        self._autostart_list_click_map: Dict[int, int] = {}
        self._autostart_list_x_range: Tuple[int, int] = (0, 0)

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
                "Abre la ventana con selector desplegable de apps o entrada de comando",
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

    def _build_bar_section_items(self) -> List[SectionItem]:
        """Construye los controles de la pestaña Barra Superior de Omarchy (~/.config/omarchy/shell.json)."""
        items = [
            SectionItem("bar:visible", "Mostrar barra superior", "Muestra u oculta la barra superior de Omarchy en vivo", "toggle"),
            SectionItem("bar:position", "Posicion de la barra", "Borde de la pantalla donde se ubica la barra", "select", options=["top", "bottom", "left", "right"]),
            SectionItem("bar:transparent", "Fondo transparente", "Hace transparente la superficie de la barra superior", "toggle"),
            SectionItem("bar:center_anchor", "Widget ancla central", "Widget que permanece centrado en la barra", "select", options=["omarchy.clock", "omarchy.workspaces", "none"]),
            SectionItem(
                "bar:clock_format",
                "Formato del reloj",
                "Formato principal de fecha y hora en la barra",
                "select",
                options=["ddd d MMM h:mm AP", "ddd d MMM HH:mm", "HH:mm", "h:mm AP", "HH:mm:ss"],
            ),
            SectionItem(
                "bar:clock_alt_format",
                "Formato alternativo del reloj",
                "Formato secundario mostrado al hacer clic sobre el reloj",
                "select",
                options=["d MMMM 'W'ww yyyy", "dddd, d MMMM yyyy", "yyyy-MM-dd"],
            ),
            SectionItem("bar:idle_screensaver", "Salvapantallas por inactividad (s)", "Segundos antes de activar el salvapantallas (0 = desactivado)", "stepper", 0, 1800, 30),
            SectionItem("bar:idle_lock", "Bloqueo de sesion por inactividad (s)", "Segundos antes de bloquear la sesion (0 = desactivado)", "stepper", 0, 3600, 60),
            SectionItem("action:reset_bar_defaults", "Restaurar barra por defecto", "Ejecuta 'omarchy-bar defaults' para recuperar el diseño original", "action"),
            SectionItem("action:restart_shell", "Reiniciar barra y shell Omarchy", "Recarga el shell grafico de Omarchy completamente", "action"),
            SectionItem(
                "header:bar_widgets",
                "WIDGETS DE LA BARRA SUPERIOR",
                "Elige en que seccion mostrar cada widget mediante menu desplegable (off / left / center / right)",
                "header",
            ),
        ]
        for w_id, s_key, w_label, _ in ConfigSync.BAR_WIDGETS:
            items.append(
                SectionItem(
                    f"bar_widget:{s_key}",
                    w_label,
                    f"Ubicacion del widget '{w_id}' en la barra (off = oculto)",
                    "select",
                    options=["off", "left", "center", "right"],
                )
            )
        return items

    def _build_themes_section_items(self) -> List[SectionItem]:
        """Construye dinámicamente los controles de la sección Temas Omarchy y las tarjetas de temas guardados."""
        self.available_themes = self.theme_engine.list_available_themes()
        themes = self.available_themes if self.available_themes else ["tokyo-night", "lizarbe", "catppuccin", "rose-pine"]

        cur_accent = self.settings.get("omarchy_theme_accent", "#E31B23")
        accent_opts = list(dict.fromkeys([cur_accent, "#7aa2f7", "#E31B23", "#89b4fa", "#1e66f5", "#2DB872", "#E5A83B", "#f38ba8", "#94e2d5"]))

        cur_bg = self.settings.get("omarchy_theme_bg", "#08080B")
        bg_opts = list(dict.fromkeys([cur_bg, "#1a1b26", "#08080B", "#1e1e2e", "#161622", "#101019", "#ffffff", "#eff1f5"]))

        cur_fg = self.settings.get("omarchy_theme_fg", "#d8d8d8")
        fg_opts = list(dict.fromkeys([cur_fg, "#a9b1d6", "#d8d8d8", "#cdd6f4", "#ffffff", "#000000", "#1a1a1a"]))

        cur_sel = self.settings.get("omarchy_theme_sel", "#45475a")
        sel_opts = list(dict.fromkeys([cur_sel, "#292e42", "#45475a", "#E31B23", "#c0c0c0", "#ccd0da", "#313244"]))

        cur_icons = self.settings.get("omarchy_icons", "Adwaita")
        icon_opts = list(dict.fromkeys([cur_icons, "Yaru-blue", "Yaru-red", "Yaru-purple", "Papirus-Dark", "Adwaita", "Lizarbe-Red"]))

        items = [
            SectionItem(
                "action:create_theme",
                "Crear nuevo tema Omarchy",
                "Crea y registra un nuevo tema clonando estructura y fondos de una plantilla",
                "action",
            ),
            SectionItem(
                "action:clone_theme",
                "Duplicar tema actual como nuevo",
                f"Clona '{self.theme_engine.current_theme}' con otro nombre para personalizarlo",
                "action",
            ),
            SectionItem("omarchy:theme", "Tema activo / Seleccionar tema", "Despliega la lista completa de temas para activar cualquiera", "select", options=themes),
            SectionItem("omarchy:theme_mode", "Modo del tema (dark / light)", "Edita el modo en el tema actual y en el original", "select", options=["dark", "light"]),
            SectionItem("omarchy:theme_accent", "Color de acento (Accent)", "Edita el color de acento en el tema actual y original", "select", options=accent_opts),
            SectionItem("omarchy:theme_bg", "Color de fondo (Background)", "Edita el color de fondo en el tema actual y original", "select", options=bg_opts),
            SectionItem("omarchy:theme_fg", "Color de texto (Foreground)", "Edita el color de texto en el tema actual y original", "select", options=fg_opts),
            SectionItem("omarchy:theme_sel", "Color de seleccion (Selection)", "Edita el color de seleccion en el tema actual y original", "select", options=sel_opts),
            SectionItem("omarchy:icons", "Paquete de iconos (icons.theme)", "Edita el paquete de iconos del tema", "select", options=icon_opts),
            SectionItem("action:custom_theme_hex", "Escribir color Hex personalizado", "Ingresa un codigo #RRGGBB exacto para editar el tema", "action"),
            SectionItem(
                "header:saved_themes",
                "TEMAS GUARDADOS EN EL SISTEMA",
                "Tarjetas de temas personalizados en ~/.config/omarchy/themes (Clic/Enter: Activar │ Supr: Eliminar)",
                "header",
            ),
        ]

        user_themes = self.theme_engine.list_user_themes()
        for u_name in user_themes:
            info = self.theme_engine.get_theme_info(u_name)
            t_mode = info.get("mode", "dark")
            t_icons = info.get("icon_theme", "Adwaita")
            items.append(
                SectionItem(
                    f"user_theme:item:{u_name}",
                    u_name,
                    f"Modo: {t_mode} │ Iconos: {t_icons} │ Supr/Del: Eliminar",
                    "theme_card",
                )
            )

        return items

    def _get_monitor_mode_options(self) -> List[str]:
        """Obtiene los modos reales soportados por el monitor activo desde hyprctl."""
        opts = ["preferred"]
        if self.monitors:
            avail = self.monitors[0].get("availableModes", [])
            for m in avail:
                if isinstance(m, str) and m not in opts:
                    opts.append(m)
        cur = str(self.settings.get("monitor_mode", "1920x1080@60.00Hz"))
        if cur and cur not in opts:
            opts.insert(0, cur)
        if len(opts) <= 1:
            opts.extend(["1920x1080@60.00Hz", "1920x1080@75.00Hz", "2560x1440@144.00Hz", "1280x720@60.00Hz"])
        return opts[:24]

    def _init_section_items(self) -> Dict[str, List[SectionItem]]:
        themes = self.available_themes if self.available_themes else ["tokyo-night", "rose-pine", "lizarbe", "white", "catppuccin"]
        mon_modes = self._get_monitor_mode_options()

        return {
            "general": [
                SectionItem("general:gaps_in", "Inner gaps (gaps_in)", "Separación entre ventanas en píxeles", "stepper", 0, 30, 1),
                SectionItem("general:gaps_out", "Outer gaps (gaps_out)", "Separación respecto a los bordes de la pantalla", "stepper", 0, 50, 1),
                SectionItem("general:border_size", "Border size", "Grosor de la línea del borde de ventanas en píxeles", "stepper", 0, 10, 1),
                SectionItem("general:resize_on_border", "Resize on border", "Permite redimensionar arrastrando los bordes con el ratón", "toggle"),
                SectionItem("general:extend_border_grab_area", "Extend border grab area", "Píxeles extra alrededor del borde para facilitar el agarre", "stepper", 0, 30, 1),
                SectionItem("general:hover_icon_on_border", "Hover icon on border", "Muestra el icono de redimensionado al pasar el cursor por el borde", "toggle"),
                SectionItem("general:layout", "Layout principal", "Algoritmo de mosaico global (dwindle / master / scrolling)", "select", options=["dwindle", "master", "scrolling"]),
                SectionItem("general:allow_tearing", "Allow tearing", "Permite screen tearing para menor latencia en juegos", "toggle"),
                SectionItem("general:no_focus_fallback", "No focus fallback", "No salta el foco a otra ventana cuando no hay ventana en esa dirección", "toggle"),
                SectionItem("general:snap:enabled", "Enable floating snap", "Ajuste magnético automático para ventanas flotantes", "toggle"),
                SectionItem("general:snap:window_gap", "Snap window gap", "Distancia en píxeles para acoplar ventanas flotantes entre sí", "stepper", 0, 40, 2),
                SectionItem("general:snap:monitor_gap", "Snap monitor gap", "Distancia en píxeles para acoplar ventanas a los bordes del monitor", "stepper", 0, 40, 2),
                SectionItem("general:snap:border_overlap", "Snap border overlap", "Superpone un borde al acoplar dos ventanas flotantes", "toggle"),
            ],
            "decoration": [
                SectionItem("decoration:rounding", "Rounding", "Radio de esquinas redondeadas en píxeles (0 = recto)", "stepper", 0, 30, 1),
                SectionItem("decoration:rounding_power", "Rounding power (Squircle)", "Curvatura de esquina superelíptica (2.0 = círculo, 4.0 = squircle)", "slider", 1.0, 5.0, 0.25),
                SectionItem("decoration:active_opacity", "Active opacity", "Opacidad de la ventana enfocada (1.0 = opaco)", "slider", 0.1, 1.0, 0.05),
                SectionItem("decoration:inactive_opacity", "Inactive opacity", "Opacidad de ventanas inactivas (1.0 = opaco)", "slider", 0.1, 1.0, 0.05),
                SectionItem("decoration:fullscreen_opacity", "Fullscreen opacity", "Opacidad de ventanas en pantalla completa", "slider", 0.1, 1.0, 0.05),
                SectionItem("decoration:dim_inactive", "Dim inactive", "Oscurece suavemente las ventanas no enfocadas", "toggle"),
                SectionItem("decoration:dim_strength", "Dim strength", "Intensidad del oscurecimiento en ventanas inactivas", "slider", 0.0, 1.0, 0.05),
                SectionItem("decoration:dim_special", "Dim special workspace", "Oscurecimiento del fondo al abrir un workspace especial", "slider", 0.0, 1.0, 0.05),
                SectionItem("decoration:blur:enabled", "Blur enabled", "Desenfoque de fondo tipo Kawase para ventanas translúcidas", "toggle"),
                SectionItem("decoration:blur:size", "Blur size", "Radio del algoritmo de desenfoque (mayor = más difuso)", "stepper", 1, 20, 1),
                SectionItem("decoration:blur:passes", "Blur passes", "Número de pasadas de filtrado Kawase", "stepper", 1, 6, 1),
                SectionItem("decoration:blur:new_optimizations", "Blur optimizations", "Activa optimizaciones de rendimiento para el desenfoque", "toggle"),
                SectionItem("decoration:blur:xray", "Blur X-Ray", "Las ventanas flotantes desenfocan directamente el fondo de pantalla", "toggle"),
                SectionItem("decoration:blur:ignore_opacity", "Blur ignore opacity", "Calcula el desenfoque ignorando la opacidad de la ventana", "toggle"),
                SectionItem("decoration:blur:vibrancy", "Blur vibrancy", "Saturación de colores en áreas desenfocadas", "slider", 0.0, 1.0, 0.05),
                SectionItem("decoration:shadow:enabled", "Drop shadows", "Habilita sombras proyectadas bajo las ventanas", "toggle"),
                SectionItem("decoration:shadow:range", "Shadow range", "Tamaño del radio de la sombra en píxeles", "stepper", 1, 40, 1),
                SectionItem("decoration:shadow:render_power", "Shadow render power", "Caída de degradado de la sombra (1 = suave, 4 = intensa)", "stepper", 1, 4, 1),
                SectionItem("decoration:shadow:sharp", "Sharp shadows", "Dibuja sombras nítidas sin difuminado", "toggle"),
            ],
            "animations": [
                SectionItem("animations:enabled", "Enable animations", "Habilita las transiciones y animaciones globales de Hyprland", "toggle"),
                SectionItem("animations:workspace_wraparound", "Workspace wraparound", "Anima el salto del último escritorio al primero como continuo", "toggle"),
                SectionItem("animations:preset", "Animation preset", "Perfil global de velocidad de curvas (omarchy / smooth / snappy / minimal)", "select", options=["omarchy", "smooth", "snappy", "minimal"]),
                SectionItem("animations:windows", "Windows style", "Estilo al abrir y cerrar ventanas (hl.animation windowsIn/Out)", "select", options=["popin 87%", "popin 80%", "slide", "gnomed"]),
                SectionItem("animations:windows_speed", "Windows speed", "Velocidad base de la animación de ventanas", "slider", 1.0, 10.0, 0.5),
                SectionItem("animations:fade_enabled", "Enable fade", "Habilita efectos de desvanecimiento (fade) en ventanas y capas", "toggle"),
                SectionItem("animations:layers", "Layers style", "Estilo de animación para paneles y menús superpuestos", "select", options=["fade", "slide", "popin 80%"]),
                SectionItem("animations:workspaces_enabled", "Animate workspaces", "Activa la animación al cambiar de espacio de trabajo", "toggle"),
                SectionItem("animations:workspaces", "Workspaces style", "Estilo de transición entre escritorios", "select", options=["slide", "slidevert", "fade", "slidefade 20%"]),
                SectionItem("animations:special", "Special workspace style", "Estilo de transición del escritorio especial (scratchpad)", "select", options=["slidevert", "slide", "fade"]),
            ],
            "cursor": [
                SectionItem("cursor:size", "Cursor size (XCURSOR_SIZE)", "Tamaño del puntero en píxeles (16 / 20 / 24 / 28 / 32 / 48)", "select", options=["16", "20", "24", "28", "32", "48"]),
                SectionItem("cursor:no_hardware_cursors", "Disable HW cursors", "Usa cursor por software (evita parpadeos o artefactos en GPUs)", "toggle"),
                SectionItem("cursor:inactive_timeout", "Inactive timeout", "Segundos de inactividad antes de ocultar el cursor (0 = nunca)", "stepper", 0, 30, 1),
                SectionItem("cursor:hide_on_key_press", "Hide on key press", "Oculta automáticamente el puntero al empezar a escribir", "toggle"),
                SectionItem("cursor:hide_on_touch", "Hide on touch", "Oculta el puntero al interactuar con pantalla táctil", "toggle"),
                SectionItem("cursor:warp_on_change_workspace", "Warp on workspace change", "Mueve el cursor a la ventana activa al cambiar de escritorio (0/1/2)", "stepper", 0, 2, 1),
                SectionItem("cursor:zoom_factor", "Zoom factor", "Factor de lupa alrededor del puntero (1.0 = sin zoom)", "slider", 1.0, 3.0, 0.25),
                SectionItem("cursor:zoom_rigid", "Zoom rigid", "El área ampliada sigue rígidamente el movimiento del puntero", "toggle"),
            ],
            "keybinds": [
                SectionItem("input:kb_layout", "Keyboard layout (kb_layout)", "Distribución de teclado XKB (ej. us, latam, es)", "select", options=["us", "latam", "es", "us,latam", "us,es", "br", "fr", "de"]),
                SectionItem("input:kb_variant", "Keyboard variant (kb_variant)", "Variante de distribución (vacío, intl, deadtilde, nodeadkeys)", "select", options=["none", "intl", "deadtilde", "nodeadkeys", "dvorak", "colemak"]),
                SectionItem("input:compose_key", "Tecla Bloq Mayús / Compose", "Alt Gr = Compose (Bloq Mayús normal) vs Omarchy default", "select", options=["Alt Gr (Compose)", "Bloq Mayús (Compose)"]),
                SectionItem("action:fix_caps", "Aplicar corrección Bloq Mayús", "Guarda la opción en input.lua y libera Bloq Mayús de inmediato", "action"),
                SectionItem("input:repeat_rate", "Keyboard repeat rate", "Frecuencia de repetición de teclas mantenidas (Hz)", "stepper", 10, 100, 5),
                SectionItem("input:repeat_delay", "Keyboard repeat delay", "Retardo antes de iniciar repetición continua (ms)", "stepper", 150, 600, 25),
                SectionItem("input:numlock_by_default", "Numlock by default", "Activa el bloque numérico automáticamente al iniciar sesión", "toggle"),
                SectionItem("binds:omarchy_default_bindings", "Omarchy default bindings", "Carga los atajos predeterminados del sistema en hyprland.lua", "toggle"),
                SectionItem("binds:omarchy_preinstalled_bindings", "Preinstalled app bindings", "Mantiene atajos para aplicaciones y webapps preinstaladas", "toggle"),
                SectionItem("binds:hide_special", "Hide special on workspace change", "Cierra el scratchpad al cambiar a otro escritorio normal", "toggle"),
                SectionItem("binds:workspace_back_forth", "Workspace back and forth", "Pulsar el número del escritorio actual regresa al escritorio previo", "toggle"),
                SectionItem("binds:allow_cycles", "Allow workspace cycles", "Permite encadenar saltos al navegar por el historial de escritorios", "toggle"),
            ],
            "devices": [
                SectionItem("input:follow_mouse", "Follow mouse (0-3)", "Foco al mover cursor (0=Off, 1=Total, 2=Cursor suelto, 3=Separado)", "stepper", 0, 3, 1),
                SectionItem("input:mouse_refocus", "Mouse refocus", "Vuelve a enfocar la ventana bajo el cursor al cruzar bordes", "toggle"),
                SectionItem("input:sensitivity", "Mouse sensitivity", "Velocidad del puntero libinput (-1.0 a 1.0)", "slider", -1.0, 1.0, 0.05),
                SectionItem("input:accel_profile", "Acceleration profile", "Curva de aceleración (flat = directa 1:1, adaptive = dinámica)", "select", options=["flat", "adaptive"]),
                SectionItem("input:mouse_natural_scroll", "Mouse natural scroll", "Invierte el sentido de desplazamiento de la rueda del ratón", "toggle"),
                SectionItem("input:left_handed", "Left-handed mouse", "Intercambia los botones izquierdo y derecho del ratón", "toggle"),
                SectionItem("input:touchpad:natural_scroll", "Touchpad natural scroll", "Desplazamiento inverso natural en el touchpad", "toggle"),
                SectionItem("input:touchpad:scroll_factor", "Touchpad scroll factor", "Multiplicador de velocidad de desplazamiento en el touchpad", "slider", 0.1, 2.0, 0.1),
                SectionItem("input:touchpad:clickfinger_behavior", "Clickfinger behavior", "Clic con 2 dedos = derecho, 3 dedos = central", "toggle"),
                SectionItem("input:touchpad:tap-to-click", "Tap to click", "Tocar suavemente el touchpad produce un clic izquierdo", "toggle"),
                SectionItem("input:touchpad:disable_while_typing", "Disable while typing", "Desactiva el touchpad mientras se escribe en el teclado", "toggle"),
                SectionItem("input:touchpad:drag_3fg", "Three-finger drag (drag_3fg)", "Arrastrar ventanas con 3 dedos (0=Off, 1=Activo, 2=Con bloqueo)", "stepper", 0, 2, 1),
                SectionItem("gestures:workspace_swipe", "3-finger workspace swipe", "Gesto horizontal de 3 dedos para cambiar de escritorio (hl.gesture)", "toggle"),
            ],
            "monitors": [
                SectionItem("display:scale", "Monitor scale (HiDPI)", "Factor de escala de la pantalla activa en monitors.lua", "select", options=self.scales),
                SectionItem("display:mode", "Display resolution & Hz", "Resolución y tasa de refresco detectadas para el monitor", "select", options=mon_modes),
                SectionItem("display:transform", "Rotación / Transform (0-3)", "Orientación (0=Normal, 1=90°, 2=180°, 3=270°)", "select", options=["0 (Normal)", "1 (90 grados)", "2 (180 grados)", "3 (270 grados)"]),
                SectionItem("display:gdk_scale", "GDK_SCALE (Apps GTK)", "Escala entera para aplicaciones GTK/X11 (1 o 2)", "select", options=["1", "2"]),
                SectionItem("display:vrr", "Adaptive Sync / VRR", "Frecuencia variable FreeSync/G-Sync (0=Off, 1=On, 2=Fullscreen)", "select", options=["0 (Desactivado)", "1 (Siempre activo)", "2 (Solo pantalla completa)"]),
                SectionItem("display:xwayland_zero_scaling", "XWayland force zero scaling", "Evita el desenfoque en aplicaciones XWayland con HiDPI", "toggle"),
                SectionItem("action:save_monitor", "Guardar en monitors.lua", "Escribe y aplica la configuración del monitor en ~/.config/hypr/monitors.lua", "action"),
            ],
            "workspaces": [
                SectionItem("workspace:count", "Persistent workspaces", "Cantidad de escritorios fijos creados con hl.workspace_rule", "stepper", 1, 10, 1),
                SectionItem("workspace:layout_toggle", "Default workspace layout", "Algoritmo asignado a los escritorios (dwindle / scrolling / master)", "select", options=["dwindle", "scrolling", "master"]),
                SectionItem("misc:focus_on_activate", "Focus on activate", "Enfoca automáticamente las aplicaciones que solicitan atención", "toggle"),
                SectionItem("misc:dpms_key", "Key press enables DPMS", "Despierta la pantalla suspendida al pulsar cualquier tecla", "toggle"),
                SectionItem("misc:dpms_mouse", "Mouse move enables DPMS", "Despierta la pantalla suspendida al mover el ratón", "toggle"),
                SectionItem("misc:focus_under_fs", "On focus under fullscreen", "Al abrir ventana sobre fullscreen (0=Nada, 1=Reemplazar, 2=Salir FS)", "stepper", 0, 2, 1),
                SectionItem("misc:animate_resizes", "Animate manual resizes", "Anima suavemente el redimensionado manual con el ratón", "toggle"),
                SectionItem("misc:animate_dragging", "Animate window dragging", "Anima las ventanas mientras se arrastran con el puntero", "toggle"),
            ],
            "layouts": [
                SectionItem("dwindle:force_split", "Dwindle force split", "Dirección de división (0=Sigue ratón, 1=Izq/Arriba, 2=Der/Abajo)", "stepper", 0, 2, 1),
                SectionItem("dwindle:preserve_split", "Dwindle preserve split", "Conserva la orientación de división independientemente del contenido", "toggle"),
                SectionItem("dwindle:smart_split", "Dwindle smart split", "Divide según la posición exacta del cursor dentro de la ventana", "toggle"),
                SectionItem("dwindle:smart_resizing", "Dwindle smart resizing", "Determina qué borde redimensionar según la dirección del ratón", "toggle"),
                SectionItem("dwindle:split_ratio", "Dwindle default split ratio", "Proporción de tamaño al dividir ventanas (1.0 = 50%/50%)", "slider", 0.5, 1.5, 0.05),
                SectionItem("layout:single_window_aspect", "Single window aspect ratio", "Limita el ancho de una ventana única en pantallas ultrawide", "select", options=["0 0", "1 1", "4 3", "16 9"]),
                SectionItem("master:new_status", "Master new status", "Posición de nuevas ventanas en layout Master (master / slave / inherit)", "select", options=["master", "slave", "inherit"]),
                SectionItem("master:mfact", "Master factor (mfact)", "Porcentaje de pantalla que ocupa la columna principal Master", "slider", 0.20, 0.80, 0.05),
                SectionItem("master:orientation", "Master orientation", "Ubicación del área principal Master en la pantalla", "select", options=["left", "right", "top", "bottom", "center"]),
                SectionItem("scrolling:column_width", "Scrolling column width", "Ancho relativo de cada columna en layout Scrolling (0.49 = 2 cols)", "slider", 0.25, 1.0, 0.02),
                SectionItem("group:groupbar:enabled", "Groupbar enabled", "Muestra la barra de pestañas superior en ventanas agrupadas", "toggle"),
                SectionItem("group:groupbar:font_size", "Groupbar font size", "Tamaño de fuente en las pestañas de grupos de ventanas", "stepper", 8, 20, 1),
                SectionItem("group:groupbar:height", "Groupbar height", "Altura en píxeles de la barra de grupos", "stepper", 14, 36, 2),
                SectionItem("group:groupbar:gradients", "Groupbar gradients", "Dibuja fondos con estilo degradado en las pestañas de grupo", "toggle"),
            ],
            "rules": [
                SectionItem("rules:terminal_scroll", "Terminal touchpad scroll", "Velocidad de scroll touchpad en Alacritty/Kitty/Foot (o.window)", "slider", 0.2, 3.0, 0.1),
                SectionItem("rules:browser_opaque", "Opaque browsers", "Desactiva la transparencia global en navegadores Chromium/Firefox", "toggle"),
                SectionItem("rules:media_opaque", "Opaque media & video apps", "Mantiene 100% opacos reproductores y editores de vídeo (MPV, VLC, OBS)", "toggle"),
                SectionItem("rules:pavucontrol_float", "Float Pavucontrol", "Abre el mezclador de sonido Pavucontrol como ventana flotante centrada", "toggle"),
                SectionItem("rules:calculator_float", "Float Calculator", "Abre la calculadora en modo ventana flotante centrada", "toggle"),
                SectionItem("rules:pip_float", "Picture-in-Picture float & pin", "Fija las ventanas Picture-in-Picture flotantes en esquina", "toggle"),
                SectionItem("rules:steam_float", "Float Steam windows", "Abre Steam y su lista de amigos como ventanas flotantes", "toggle"),
                SectionItem("rules:localsend_float", "Float LocalSend", "Abre LocalSend en ventana flotante centrada de 1100x700", "toggle"),
            ],
            "autostart": self._build_autostart_section_items(),
            "bar": self._build_bar_section_items(),
            "themes": self._build_themes_section_items(),
            "omarchy": [
                SectionItem("omarchy:theme", "Active Omarchy Theme", "Selecciona y aplica rápidamente el tema global de Omarchy", "select", options=themes),
                SectionItem("action:next_wallpaper", "Cambiar fondo de pantalla", "Alterna al siguiente wallpaper del tema Omarchy activo", "action"),
                SectionItem("action:toggle_bar", "Alternar barra superior Omarchy", "Muestra u oculta la barra superior de Omarchy", "action"),
                SectionItem("action:toggle_nightlight", "Alternar luz nocturna", "Activa o desactiva el filtro cálido hyprsunset", "action"),
                SectionItem("action:apply_lizarbe_full", "Aplicar Setup Lizarbe", "Configura el tema Lizarbe, logo Fastfetch y Bloq Mayús", "action"),
                SectionItem("action:install_hook", "Registrar hook en 'omarchy update'", "Mantiene Meca sincronizado al actualizar el sistema", "action"),
            ],
        }

    def run(self) -> None:
        """Ciclo principal TUI en modo crudo y ventana flotante rectangular vertical (más altura que anchura)."""
        if not sys.stdin.isatty():
            print("Error: meca debe ejecutarse en una terminal TTY.")
            return

        # Establecer título de ventana para que coincida con la regla vertical de Hyprland
        sys.stdout.write("\033]0;MECA HyprConfig\007\033]2;MECA HyprConfig\007")
        sys.stdout.flush()

        # Convertir la ventana de terminal activa en flotante rectangular vertical (680x960: más altura que anchura)
        self._was_tiled = HyprIPC.ensure_floating_centered(width=680, height=960)

        fd = sys.stdin.fileno()
        self.orig_termios = termios.tcgetattr(fd)

        try:
            tty.setraw(fd)
            # Alternate screen buffer, ocultar cursor, desactivar auto-wrap (?7l) y habilitar ratón SGR con hover (?1003h)
            sys.stdout.write("\033[?1049h\033[?25l\033[?7l\033[?1000h\033[?1002h\033[?1003h\033[?1006h\033[2J")
            sys.stdout.flush()

            while self.running:
                self._frame_count += 1
                if self._frame_count == 2:
                    # Re-aplicar geometría vertical por si la terminal tardó unos ms en mapearse en Wayland
                    HyprIPC.ensure_floating_centered(width=680, height=960)
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

    def _get_sidebar_width(self, cols: int) -> int:
        return 22 if cols < 95 else 26

    def render(self) -> None:
        cols, rows = shutil.get_terminal_size((84, 42))
        sidebar_w = self._get_sidebar_width(cols)
        content_w = max(30, cols - sidebar_w - 1)
        buf: List[str] = []

        # 1. Barra de Título Superior en fila exacta 1 (\033[1;1H)
        ver = HyprIPC.get_version_info()
        title_left = " MECA HyprConfig "
        unsaved_badge = " *PENDIENTE* | " if self.has_unsaved_changes() else ""
        title_right = f"{unsaved_badge}Hyprland {ver} | Tema: {self.theme_engine.current_theme} | q/Esc: Salir "
        if len(title_left) + len(title_right) > cols:
            title_right = f"Tema: {self.theme_engine.current_theme} | q/Esc: Salir "
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

        # 3. Barra Inferior de Estado en fila exacta 'rows' (con guía q/Esc: Salir)
        keys_hint = " Tab: Foco │ r: Restablecer │ c: Cancelar │ a: Aplicar │ q/Esc: Salir "
        if cols < 100:
            keys_hint = " r:Restablecer │ c:Cancelar │ a:Aplicar │ q/Esc:Salir "
        max_status_w = max(8, cols - len(keys_hint) - 1)
        status_txt = f" {self.status_message}"[:max_status_w]
        footer_space = max(0, cols - 1 - len(status_txt) - len(keys_hint))
        footer_line = (status_txt + (" " * footer_space) + keys_hint)[:cols - 1]
        buf.append(f"\033[{rows};1H" + self.theme_engine.style("bright_foreground", "muted", footer_line) + "\033[K")

        # 4. Menú desplegable (Dropdown) si está abierto sobre una opción "select"
        if self.dropdown_open and not self.modal_state:
            buf.extend(self._render_dropdown_overlay(cols, rows, sidebar_w))

        # 5. Ventana Modal (si está activa)
        if self.modal_state:
            buf.extend(self._render_modal_overlay(cols, rows))

        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    def _render_sidebar(self, width: int, max_rows: int) -> List[str]:
        """
        Renderiza el panel izquierdo sin márgenes verticales entre las opciones de cada categoría.
        Registra las filas exactas en self._sidebar_click_map para precisión de clic 1:1.
        """
        lines: List[str] = []
        current_cat = None
        self._sidebar_click_map.clear()

        for idx, (cat, sec_id, icon, title, desc) in enumerate(self.SECTIONS):
            if cat != current_cat:
                if current_cat is not None and len(lines) < max_rows:
                    lines.append(" " * width)

                current_cat = cat
                if len(lines) < max_rows:
                    lines.append(self.theme_engine.style("muted", None, f" {cat}".ljust(width)[:width], bold=True))

            if len(lines) >= max_rows:
                break

            is_sel = (idx == self.current_section_idx)
            is_hover = (idx == self.hover_sidebar_idx and not self.modal_state and not self.dropdown_open)
            is_active_pane = (self.active_pane == "sidebar" and not self.modal_state and not self.dropdown_open)

            screen_row = 2 + len(lines)
            self._sidebar_click_map[screen_row] = idx

            prefix = " ▸" if is_hover else "  "
            item_text = f"{prefix}{icon}  {title}".ljust(width)[:width]

            if is_sel and (is_active_pane or is_hover):
                line = self.theme_engine.style("bright_foreground", "soft_selection", item_text, bold=True)
            elif is_sel:
                line = self.theme_engine.style("bright_foreground", "soft_muted", item_text, bold=True)
            elif is_hover:
                line = self.theme_engine.style("bright_foreground", "soft_muted", item_text, bold=True)
            else:
                line = self.theme_engine.style("foreground", None, item_text)

            lines.append(line)

        while len(lines) < max_rows:
            lines.append(" " * width)

        return lines[:max_rows]

    def _render_theme_card_3lines(
        self,
        item: SectionItem,
        width: int,
        is_sel: bool,
        is_hover: bool,
    ) -> Tuple[str, str, str, Tuple[int, int]]:
        """
        Renderiza un tema guardado con apariencia de contenedor de tarjeta cuadrada:
        ┌──────────────────────────────────────────────────────────────────┐
        │ ■ nombre [ACTIVO]    ██ ██ ██ ██  Modo: dark    ┃ Activar │      │
        └──────────────────────────────────────────────────────────────────┘
        """
        u_name = item.name
        info = self.theme_engine.get_theme_info(u_name)
        colors = info.get("colors", {})
        mode = info.get("mode", "dark")
        is_act = (
            self.theme_engine.normalize_theme_slug(u_name)
            == self.theme_engine.normalize_theme_slug(self.theme_engine.current_theme)
        )

        card_w = max(28, width - 3)
        inner_w = card_w - 2

        border_col = "accent" if (is_sel or is_hover) else ("bright_foreground" if is_act else "muted")
        card_bg = "soft_hover" if is_hover else ("soft_selection" if is_sel else ("soft_muted" if is_act else None))

        # Construir muestras de color (swatches) reales de la paleta del tema
        swatches_styled = ""
        for c_key in ("accent", "background", "foreground", "selection"):
            hex_c = str(colors.get(c_key, "#888888"))
            r, g, b = self.theme_engine.hex_to_rgb(hex_c)
            swatches_styled += f"\033[38;2;{r};{g};{b}m██\033[0m"
            if card_bg:
                bg_r, bg_g, bg_b = self.theme_engine.hex_to_rgb(self.theme_engine.colors.get(card_bg, "#1a1b26"))
                swatches_styled += f"\033[48;2;{bg_r};{bg_g};{bg_b}m \033[0m"
            else:
                swatches_styled += " "
        swatches_vis_w = 12  # 4 * ("██" + " ")

        badge = " [ACTIVO]" if is_act else ""
        btn_txt = " [Activo] " if is_act else " [Activar] "
        btn_vis_w = len(btn_txt)

        title_str = f" ■ {u_name}{badge}"
        meta_str = f" ({mode}) "
        avail_title_w = max(8, inner_w - swatches_vis_w - btn_vis_w - len(meta_str) - 2)
        left_plain = (title_str[:avail_title_w] + meta_str).ljust(avail_title_w + len(meta_str))
        pad_mid_w = max(1, inner_w - len(left_plain) - swatches_vis_w - btn_vis_w)

        top_border = " " + self.theme_engine.style(border_col, None, "┌" + ("─" * inner_w) + "┐", bold=(is_sel or is_hover))
        bot_border = " " + self.theme_engine.style(border_col, None, "└" + ("─" * inner_w) + "┘", bold=(is_sel or is_hover))

        left_styled = self.theme_engine.style("bright_foreground", card_bg, left_plain, bold=True)
        pad_styled = self.theme_engine.style("foreground", card_bg, " " * pad_mid_w)
        btn_fg = "accent" if (is_sel or is_hover or is_act) else "bright_foreground"
        btn_styled = self.theme_engine.style(btn_fg, card_bg, btn_txt, bold=True)

        mid_line = (
            " "
            + self.theme_engine.style(border_col, None, "│", bold=(is_sel or is_hover))
            + left_styled
            + swatches_styled
            + pad_styled
            + btn_styled
            + self.theme_engine.style(border_col, None, "│", bold=(is_sel or is_hover))
        )

        return top_border, mid_line, bot_border, (1, card_w)

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
        elif sec_id == "bar":
            self.section_items["bar"] = self._build_bar_section_items()
        elif sec_id == "themes":
            self.section_items["themes"] = self._build_themes_section_items()

        items = self.section_items.get(sec_id, [])
        is_active_pane = (self.active_pane == "content" and not self.modal_state)
        content_start_x = sidebar_w + 2

        # Asegurar que selected_item_idx no apunte a un separador "header"
        if items and 0 <= self.selected_item_idx < len(items) and items[self.selected_item_idx].item_type == "header":
            if self.selected_item_idx + 1 < len(items):
                self.selected_item_idx += 1
            elif self.selected_item_idx > 0:
                self.selected_item_idx -= 1

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
            item_screen_row = 2 + len(lines)

            # 1. Separador visual de sub-sección ("header")
            if item.item_type == "header":
                hdr_title = f" ━━ {item.name} "
                rem_bars = max(2, width - len(hdr_title) - 2)
                l1 = self.theme_engine.style("accent", None, hdr_title + ("━" * rem_bars), bold=True)
                l2 = " " + self.theme_engine.fg("muted", item.desc[:width - 2])
                l3 = ""
                lines.append(l1)
                lines.append(l2)
                lines.append(l3)
                continue

            is_hover_row = (i == self.hover_item_idx and not self.modal_state and not self.dropdown_open)
            is_sel = (i == self.selected_item_idx and is_active_pane) or is_hover_row

            # 2. Contenedor con borde cuadrado / tarjeta para temas guardados ("theme_card")
            if item.item_type == "theme_card":
                t_top, t_mid, t_bot, (c_rel_start, c_rel_end) = self._render_theme_card_3lines(
                    item, width, is_sel, is_hover_row
                )
                card_x_start = content_start_x + c_rel_start
                card_x_end = content_start_x + c_rel_end
                click_info = {
                    "item_idx": i,
                    "item": item,
                    "control_range": (card_x_start, card_x_end),
                    "minus_range": (0, 0),
                    "plus_range": (0, 0),
                    "slider_range": (0, 0),
                    "row_y": item_screen_row,
                }
                self._content_click_map[item_screen_row] = click_info
                self._content_click_map[item_screen_row + 1] = click_info
                self._content_click_map[item_screen_row + 2] = click_info
                lines.append(t_top)
                lines.append(t_mid)
                lines.append(t_bot)
                continue

            # 3. Control estándar de 3 líneas
            hover_sub = self.hover_subcontrol if is_hover_row else None
            c_top, c_mid, c_bot, ctrl_vis_w = self._format_item_control_3lines(item, is_sel, hover_sub)
            left_max_w = max(12, width - ctrl_vis_w - 3)

            control_x_start = content_start_x + left_max_w + 1
            control_x_end = control_x_start + ctrl_vis_w - 1

            click_info = {
                "item_idx": i,
                "item": item,
                "control_range": (control_x_start, control_x_end),
                "minus_range": (control_x_start, control_x_start + 4),
                "plus_range": (control_x_end - 4, control_x_end),
                "slider_range": (control_x_start, control_x_start + 10),
                "row_y": item_screen_row,
            }
            self._content_click_map[item_screen_row] = click_info
            self._content_click_map[item_screen_row + 1] = click_info
            self._content_click_map[item_screen_row + 2] = click_info

            if is_sel:
                l1_raw = f" ▌ {item.name}"[:left_max_w].ljust(left_max_w)
                l2_raw = f" ▌ └─ {item.desc}"[:left_max_w].ljust(left_max_w)
                l1_styled = self.theme_engine.style("bright_foreground", "soft_selection", l1_raw, bold=True)
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

    def _open_dropdown_for_item(self, item: SectionItem, anchor_y: int = 8, anchor_x: int = 45) -> None:
        """Abre el menú desplegable (dropdown) para un control de tipo 'select'."""
        if not item.options:
            return
        self.dropdown_open = True
        self.dropdown_item = item
        self.dropdown_options = list(item.options)
        cur_val = str(self._get_item_value(item))
        try:
            self.dropdown_idx = self.dropdown_options.index(cur_val)
        except ValueError:
            self.dropdown_idx = 0
        self.dropdown_scroll = max(0, self.dropdown_idx - 3)
        self.hover_dropdown_idx = None
        self.dropdown_anchor_y = anchor_y
        self.dropdown_anchor_x = anchor_x

    def _render_dropdown_overlay(self, cols: int, rows: int, sidebar_w: int) -> List[str]:
        """Renderiza el menú desplegable interactivo sobre la opción seleccionada."""
        self._dropdown_row_map.clear()
        if not self.dropdown_item or not self.dropdown_options:
            return []

        opts = self.dropdown_options
        max_vis = min(8, len(opts), max(4, rows - 8))
        if self.dropdown_idx < self.dropdown_scroll:
            self.dropdown_scroll = self.dropdown_idx
        elif self.dropdown_idx >= self.dropdown_scroll + max_vis:
            self.dropdown_scroll = self.dropdown_idx - max_vis + 1
        self.dropdown_scroll = max(0, min(self.dropdown_scroll, max(0, len(opts) - max_vis)))

        max_opt_len = max(len(str(o)) for o in opts)
        inner_w = max(20, min(42, max_opt_len + 8))
        box_w = inner_w + 2
        box_h = max_vis + 2

        # Posicionar el desplegable alineado a la derecha del panel de contenido, justo debajo o encima del control
        start_x = max(sidebar_w + 3, cols - box_w - 2)
        start_y = self.dropdown_anchor_y + 3
        if start_y + box_h >= rows - 1:
            start_y = max(3, self.dropdown_anchor_y - box_h)

        self._dropdown_box_bounds = (start_y, start_y + box_h - 1, start_x, start_x + box_w - 1)
        cur_val = str(self._get_item_value(self.dropdown_item))

        overlay: List[str] = []
        hdr_hint = " ▲ " if self.dropdown_scroll > 0 else "───"
        top_line = "┌" + ("─" * (inner_w - 3)) + hdr_hint + "┐"
        overlay.append(f"\033[{start_y};{start_x}H" + self.theme_engine.style("accent", "background", top_line, bold=True))

        for r_off in range(max_vis):
            opt_idx = self.dropdown_scroll + r_off
            scr_y = start_y + 1 + r_off
            opt_str = str(opts[opt_idx])
            self._dropdown_row_map[scr_y] = opt_idx

            is_sel = (opt_idx == self.dropdown_idx)
            is_hov = (opt_idx == self.hover_dropdown_idx)
            is_cur = (opt_str == cur_val)

            check = "✓" if is_cur else ("▸" if (is_sel or is_hov) else " ")
            row_txt = f" {check} {opt_str}"[:inner_w].ljust(inner_w)
            row_bg = "soft_hover" if is_hov else ("soft_selection" if is_sel else "background")
            row_fg = "bright_foreground" if (is_sel or is_hov or is_cur) else "foreground"

            overlay.append(
                f"\033[{scr_y};{start_x}H"
                + self.theme_engine.style("accent", "background", "┃", bold=True)
                + self.theme_engine.style(row_fg, row_bg, row_txt, bold=(is_sel or is_hov or is_cur))
                + self.theme_engine.style("accent", "background", "│", bold=True)
            )

        ftr_hint = " ▼ " if (self.dropdown_scroll + max_vis < len(opts)) else "━━━"
        bot_line = "┗" + ("━" * (inner_w - 3)) + ftr_hint + "┙"
        overlay.append(f"\033[{start_y + max_vis + 1};{start_x}H" + self.theme_engine.style("accent", "background", bot_line, bold=True))
        return overlay

    def _render_3d_buttons(self, width: int, btn_top_screen_y: int, content_start_x: int) -> List[str]:
        """
        Dibuja los 3 botones inferiores compactos de 3 líneas con bisel 3D Unicode y destello suave:
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
        left_pad = max(1, width - total_btns_w - 2)

        row0_parts = [" " * left_pad]
        row1_parts = [" " * left_pad]
        row2_parts = [" " * left_pad]

        cur_rel_x = left_pad
        is_btn_pane = (self.active_pane == "buttons" and not self.modal_state and not self.dropdown_open)

        for btn_key, btn_idx, label in buttons_spec:
            inner_w = len(label)
            btn_w = inner_w + 2
            is_hover_btn = (self.hover_button_key == btn_key and not self.modal_state and not self.dropdown_open)
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
                inner_styled = self.theme_engine.style("bright_foreground", "soft_hover", label, bold=True)
            elif is_sel:
                inner_styled = self.theme_engine.style("bright_foreground", "soft_selection", label, bold=True)
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
        de 3 líneas (┌───┐ / ┃ - │ / ┗━━━┙) con destello suave (soft_hover / soft_selection).
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

            m_bg = "soft_hover" if m_hov else ("soft_selection" if is_sel else None)
            p_bg = "soft_hover" if p_hov else ("soft_selection" if is_sel else None)

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
            mark_bg = "soft_hover" if c_hov else ("soft_selection" if (is_sel or is_on) else None)
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
            c_hov = (hover_sub == "control") or (self.dropdown_open and self.dropdown_item == item)
            c_top = self.theme_engine.style("accent" if c_hov else b_col, None, "┌" + ("─" * inner_w) + "┐", bold=c_hov)
            inner_bg = "soft_hover" if c_hov else ("soft_selection" if is_sel else None)
            inner_s = self.theme_engine.style("bright_foreground", inner_bg, raw_lbl, bold=(is_sel or c_hov))
            c_mid = self.theme_engine.fg("accent" if c_hov else sh_col, "┃") + inner_s + self.theme_engine.fg(b_col, "│")
            c_bot = self.theme_engine.fg("accent" if c_hov else sh_col, "┗" + ("━" * inner_w) + "┙")
            return c_top, c_mid, c_bot, inner_w + 2

        elif item.item_type == "action":
            raw_lbl = " Activar " if item.key.startswith("user_theme:item:") else " Ejecutar "
            inner_w = len(raw_lbl)
            c_hov = (hover_sub == "control")
            c_top = self.theme_engine.style("accent" if c_hov else b_col, None, "┌" + ("─" * inner_w) + "┐", bold=c_hov)
            inner_bg = "soft_hover" if c_hov else ("soft_selection" if is_sel else None)
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

    def _get_filtered_autostart_apps(self) -> List[Dict[str, str]]:
        """Filtra la lista de aplicaciones instaladas según el texto buscado en el modal de Autostart."""
        q = self.modal_input_text.strip().lower()
        if not q:
            return self.installed_apps
        return [
            app for app in self.installed_apps
            if q in app["name"].lower() or q in app["cmd"].lower()
        ]

    def _render_modal_overlay(self, cols: int, rows: int) -> List[str]:
        """
        Renderiza ventanas modales centradas para:
        - "confirm_section_change": aplicar/descartar cambios al cambiar de sección
        - "confirm_reset": confirmar restablecimiento a valores predeterminados
        - "input_autostart": selector desplegable de aplicaciones/servicios o entrada de comando
        - "input_theme_hex": ingresar color hexadecimal personalizado para el tema Omarchy
        - "create_theme": crear y agregar un nuevo tema Omarchy
        """
        self._modal_button_click_map.clear()
        self._modal_kind_click_range = (0, 0, 0)
        self._modal_mode_click_range = (0, 0, 0)
        self._autostart_dropdown_btn_range = (0, 0, 0, 0)
        self._autostart_list_click_map.clear()

        if self.modal_state == "input_autostart":
            return self._render_autostart_modal(cols, rows)
        if self.modal_state == "create_theme":
            return self._render_create_theme_modal(cols, rows)
        if self.modal_state == "input_theme_hex":
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
            is_b_hov = (self.hover_modal_btn_idx == b_idx)
            is_b_sel = (self.modal_selected_idx == b_idx) or is_b_hov
            self._modal_button_click_map[b_idx] = (cur_x, cur_x + bw - 1)

            b_col = "bright_foreground" if is_b_sel else "foreground"
            sh_col = "accent" if is_b_sel else "muted"
            btn_bg = "soft_hover" if is_b_hov else ("soft_selection" if is_b_sel else "background")

            r0_s = self.theme_engine.style(b_col, "background", "┌" + ("─" * len(b_lbl)) + "┐", bold=is_b_sel)
            r1_s = (
                self.theme_engine.style(sh_col, "background", "┃", bold=True)
                + self.theme_engine.style("bright_foreground" if is_b_sel else "foreground", btn_bg, b_lbl, bold=is_b_sel)
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

    def _render_autostart_modal(self, cols: int, rows: int) -> List[str]:
        """
        Renderiza el modal para agregar a Autostart:
        - La selección de aplicación instalada es un selector desplegable (dropdown)
          que SOLO funciona cuando está seleccionado el tipo 'Aplicación / Servicio' ('launch').
        - Cuando se elige 'Comando / Script' ('exec'), el selector desplegable de aplicaciones
          queda deshabilitado.
        """
        is_app_mode = (self.modal_input_kind == "launch")
        if not is_app_mode:
            self.autostart_dropdown_open = False

        title = " AGREGAR A AUTOSTART (APLICACION / SERVICIO / COMANDO) "
        kind_val = (
            "Aplicacion / Servicio (o.launch_on_start)"
            if is_app_mode
            else "Comando personalizado (o.exec_on_start)  "
        )

        mw = min(66, cols - 4)
        inner_mw = mw - 2
        show_list = is_app_mode and self.autostart_dropdown_open
        list_rows = 6 if show_list else 0
        mh = 16 + list_rows
        start_x = max(2, (cols - mw) // 2)
        start_y = max(2, (rows - mh) // 2)

        overlay: List[str] = []
        top_line = "┌" + ("─" * inner_mw) + "┐"
        title_centered = title[:inner_mw].center(inner_mw)
        sep_line = "├" + ("─" * inner_mw) + "┤"
        bot_line = "┗" + ("━" * inner_mw) + "┙"

        selector_line = f"  Tipo (Tab/Clic): {kind_val} ▾".ljust(inner_mw)[:inner_mw]
        self._modal_kind_click_range = (start_y + 3, start_x + 2, start_x + inner_mw - 2)

        overlay.append(f"\033[{start_y};{start_x}H" + self.theme_engine.style("bright_foreground", "background", top_line, bold=True))
        overlay.append(f"\033[{start_y + 1};{start_x}H" + self.theme_engine.style("bright_foreground", "accent", "┃" + title_centered + "│", bold=True))
        overlay.append(f"\033[{start_y + 2};{start_x}H" + self.theme_engine.style("muted", "background", sep_line))
        overlay.append(f"\033[{start_y + 3};{start_x}H" + self.theme_engine.style("bright_foreground", "soft_selection", "┃" + selector_line + "│", bold=True))

        # Selector desplegable de aplicación (filas start_y + 4..6)
        box_w = inner_mw - 6
        filtered = self._get_filtered_autostart_apps()
        if is_app_mode:
            arrow_char = "▴" if self.autostart_dropdown_open else "▾"
            if self.autostart_selected_app_name:
                dd_txt = f" {self.autostart_selected_app_name} ({self.modal_input_text})"
            elif filtered and 0 <= self.autostart_app_idx < len(filtered):
                cur_a = filtered[self.autostart_app_idx]
                dd_txt = f" {cur_a['name']} — {cur_a['cmd']}"
            else:
                dd_txt = f" Desplegar lista de aplicaciones ({len(filtered)} disponibles)..."
            dd_inner = (dd_txt[: box_w - 3].ljust(box_w - 3)) + f" {arrow_char} "
            dd_lbl = "  Seleccionar aplicacion instalada (Clic o ↓ para desplegar):"
            dd_border_col = "accent" if self.autostart_dropdown_open else "bright_foreground"
            dd_bg = "soft_hover" if self.autostart_dropdown_open else "soft_selection"
            self._autostart_dropdown_btn_range = (start_y + 5, start_y + 6, start_x + 2, start_x + inner_mw - 2)
        else:
            dd_inner = " [Deshabilitado: solo activo en modo Aplicacion / Servicio] "[:box_w].ljust(box_w)
            dd_lbl = "  Selector desplegable de aplicacion (Inactivo en modo Comando):"
            dd_border_col = "muted"
            dd_bg = "background"
            self._autostart_dropdown_btn_range = (0, 0, 0, 0)

        dd_top = ("  ┌" + ("─" * box_w) + "┐  ").ljust(inner_mw)[:inner_mw]
        dd_mid = f"  ┃{dd_inner}│  ".ljust(inner_mw)[:inner_mw]
        dd_bot = ("  └" + ("─" * box_w) + "┘  ").ljust(inner_mw)[:inner_mw]

        overlay.append(f"\033[{start_y + 4};{start_x}H" + self.theme_engine.style("muted", "background", "┃" + dd_lbl.ljust(inner_mw)[:inner_mw] + "│"))
        overlay.append(f"\033[{start_y + 5};{start_x}H" + self.theme_engine.style(dd_border_col, "background", "┃" + dd_top + "│"))
        overlay.append(f"\033[{start_y + 6};{start_x}H" + self.theme_engine.style(dd_border_col, dd_bg, "┃" + dd_mid + "│", bold=is_app_mode))
        overlay.append(f"\033[{start_y + 7};{start_x}H" + self.theme_engine.style(dd_border_col, "background", "┃" + dd_bot + "│"))

        cur_y = start_y + 8

        # Si el menú desplegable de aplicaciones está abierto (solo en modo 'launch')
        if show_list:
            if self.autostart_app_idx >= len(filtered):
                self.autostart_app_idx = max(0, len(filtered) - 1)
            if self.autostart_app_idx < self.autostart_app_scroll:
                self.autostart_app_scroll = self.autostart_app_idx
            elif self.autostart_app_idx >= self.autostart_app_scroll + list_rows:
                self.autostart_app_scroll = self.autostart_app_idx - list_rows + 1
            self.autostart_app_scroll = max(0, min(self.autostart_app_scroll, max(0, len(filtered) - list_rows)))

            self._autostart_list_x_range = (start_x + 3, start_x + inner_mw - 3)
            for r_off in range(list_rows):
                row_y = cur_y + r_off
                f_idx = self.autostart_app_scroll + r_off
                if f_idx < len(filtered):
                    app = filtered[f_idx]
                    self._autostart_list_click_map[row_y] = f_idx
                    is_app_sel = (f_idx == self.autostart_app_idx)
                    is_app_hov = (f_idx == self.hover_autostart_app_idx)
                    marker = " ▸ " if (is_app_sel or is_app_hov) else "   "
                    name_w = max(14, box_w - 24)
                    cmd_w = max(8, box_w - name_w - 5)
                    app_name = app["name"][:name_w].ljust(name_w)
                    app_cmd = app["cmd"][:cmd_w].rjust(cmd_w)
                    item_row = f"{marker}{app_name} {app_cmd} "[:box_w].ljust(box_w)
                    row_bg = "soft_hover" if is_app_hov else ("soft_selection" if is_app_sel else "soft_muted")
                    row_fg = "bright_foreground" if (is_app_sel or is_app_hov) else "foreground"
                    overlay.append(
                        f"\033[{row_y};{start_x}H"
                        + self.theme_engine.style("foreground", "background", "┃  │")
                        + self.theme_engine.style(row_fg, row_bg, item_row, bold=(is_app_sel or is_app_hov))
                        + self.theme_engine.style("foreground", "background", "│  │")
                    )
                else:
                    empty_dd = (" " * box_w)
                    overlay.append(f"\033[{row_y};{start_x}H" + self.theme_engine.style("foreground", "background", f"┃  │{empty_dd}│  │"))
            cur_y += list_rows

        # Campo de texto para buscar aplicación (en modo launch) o escribir comando (en modo exec)
        input_lbl = (
            "  Filtrar aplicacion o editar comando a lanzar:"
            if is_app_mode
            else "  Escribir comando o script para o.exec_on_start:"
        )
        shown_txt = (self.modal_input_text + "█")[-box_w:].ljust(box_w)
        input_top = ("  ┌" + ("─" * box_w) + "┐  ").ljust(inner_mw)[:inner_mw]
        input_mid = f"  ┃{shown_txt}│  ".ljust(inner_mw)[:inner_mw]
        input_bot = ("  ┗" + ("━" * box_w) + "┙  ").ljust(inner_mw)[:inner_mw]

        overlay.append(f"\033[{cur_y};{start_x}H" + self.theme_engine.style("muted", "background", "┃" + input_lbl.ljust(inner_mw)[:inner_mw] + "│"))
        overlay.append(f"\033[{cur_y + 1};{start_x}H" + self.theme_engine.style("foreground", "background", "┃" + input_top + "│"))
        overlay.append(f"\033[{cur_y + 2};{start_x}H" + self.theme_engine.style("bright_foreground", "background", "┃" + input_mid + "│", bold=True))
        overlay.append(f"\033[{cur_y + 3};{start_x}H" + self.theme_engine.style("accent", "background", "┃" + input_bot + "│"))

        modal_btns = [
            (0, " Cancelar "),
            (1, " Agregar "),
        ]
        gap = 3
        btns_total_w = sum(len(lbl) + 2 for _, lbl in modal_btns) + gap
        pad_left = max(1, (inner_mw - btns_total_w) // 2)
        pad_right = max(0, inner_mw - btns_total_w - pad_left)

        btn_y_top = cur_y + 4
        self._modal_button_row_range = (btn_y_top, btn_y_top + 2)

        b_r0 = [self.theme_engine.style("foreground", "background", "┃" + (" " * pad_left))]
        b_r1 = [self.theme_engine.style("foreground", "background", "┃" + (" " * pad_left))]
        b_r2 = [self.theme_engine.style("foreground", "background", "┃" + (" " * pad_left))]

        cur_x = start_x + 1 + pad_left
        for b_idx, b_lbl in modal_btns:
            bw = len(b_lbl) + 2
            is_b_hov = (self.hover_modal_btn_idx == b_idx)
            is_b_sel = (self.modal_selected_idx == b_idx) or is_b_hov
            self._modal_button_click_map[b_idx] = (cur_x, cur_x + bw - 1)
            b_col = "bright_foreground" if is_b_sel else "foreground"
            sh_col = "accent" if is_b_sel else "muted"
            btn_bg = "soft_hover" if is_b_hov else ("soft_selection" if is_b_sel else "background")

            r0_s = self.theme_engine.style(b_col, "background", "┌" + ("─" * len(b_lbl)) + "┐", bold=is_b_sel)
            r1_s = (
                self.theme_engine.style(sh_col, "background", "┃", bold=True)
                + self.theme_engine.style("bright_foreground" if is_b_sel else "foreground", btn_bg, b_lbl, bold=is_b_sel)
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
        overlay.append(f"\033[{btn_y_top + 3};{start_x}H" + self.theme_engine.style("accent", "background", bot_line, bold=True))
        return overlay

    def _render_create_theme_modal(self, cols: int, rows: int) -> List[str]:
        """Renderiza la ventana modal para crear y registrar un nuevo tema Omarchy."""
        title = " CREAR NUEVO TEMA OMARCHY "
        mw = min(64, cols - 4)
        inner_mw = mw - 2
        mh = 13
        start_x = max(2, (cols - mw) // 2)
        start_y = max(2, (rows - mh) // 2)

        overlay: List[str] = []
        top_line = "┌" + ("─" * inner_mw) + "┐"
        title_centered = title.center(inner_mw)[:inner_mw]
        sep_line = "├" + ("─" * inner_mw) + "┤"
        bot_line = "┗" + ("━" * inner_mw) + "┙"

        base_line = f"  Plantilla base (↑/↓ o clic): {self.modal_base_theme} ▾".ljust(inner_mw)[:inner_mw]
        mode_line = f"  Modo inicial (Tab o clic):   {self.modal_theme_mode} ▾".ljust(inner_mw)[:inner_mw]
        self._modal_kind_click_range = (start_y + 3, start_x + 2, start_x + inner_mw - 2)
        self._modal_mode_click_range = (start_y + 4, start_x + 2, start_x + inner_mw - 2)

        box_w = inner_mw - 6
        shown_txt = (self.modal_input_text + "█")[-box_w:].ljust(box_w)
        input_top = ("  ┌" + ("─" * box_w) + "┐  ").ljust(inner_mw)[:inner_mw]
        input_mid = f"  ┃{shown_txt}│  ".ljust(inner_mw)[:inner_mw]
        input_bot = ("  ┗" + ("━" * box_w) + "┙  ").ljust(inner_mw)[:inner_mw]

        overlay.append(f"\033[{start_y};{start_x}H" + self.theme_engine.style("bright_foreground", "background", top_line, bold=True))
        overlay.append(f"\033[{start_y + 1};{start_x}H" + self.theme_engine.style("bright_foreground", "accent", "┃" + title_centered + "│", bold=True))
        overlay.append(f"\033[{start_y + 2};{start_x}H" + self.theme_engine.style("muted", "background", sep_line))
        overlay.append(f"\033[{start_y + 3};{start_x}H" + self.theme_engine.style("bright_foreground", "soft_selection", "┃" + base_line + "│", bold=True))
        overlay.append(f"\033[{start_y + 4};{start_x}H" + self.theme_engine.style("bright_foreground", "soft_muted", "┃" + mode_line + "│", bold=True))
        overlay.append(f"\033[{start_y + 5};{start_x}H" + self.theme_engine.style("muted", "background", "┃" + "  Nombre del nuevo tema (ej. cyber-night):".ljust(inner_mw)[:inner_mw] + "│"))
        overlay.append(f"\033[{start_y + 6};{start_x}H" + self.theme_engine.style("foreground", "background", "┃" + input_top + "│"))
        overlay.append(f"\033[{start_y + 7};{start_x}H" + self.theme_engine.style("bright_foreground", "background", "┃" + input_mid + "│", bold=True))
        overlay.append(f"\033[{start_y + 8};{start_x}H" + self.theme_engine.style("accent", "background", "┃" + input_bot + "│"))

        modal_btns = [
            (0, " Cancelar "),
            (1, " Crear Tema "),
        ]
        gap = 3
        btns_total_w = sum(len(lbl) + 2 for _, lbl in modal_btns) + gap
        pad_left = max(1, (inner_mw - btns_total_w) // 2)
        pad_right = max(0, inner_mw - btns_total_w - pad_left)

        btn_y_top = start_y + 9
        self._modal_button_row_range = (btn_y_top, btn_y_top + 2)

        b_r0 = [self.theme_engine.style("foreground", "background", "┃" + (" " * pad_left))]
        b_r1 = [self.theme_engine.style("foreground", "background", "┃" + (" " * pad_left))]
        b_r2 = [self.theme_engine.style("foreground", "background", "┃" + (" " * pad_left))]

        cur_x = start_x + 1 + pad_left
        for b_idx, b_lbl in modal_btns:
            bw = len(b_lbl) + 2
            is_b_hov = (self.hover_modal_btn_idx == b_idx)
            is_b_sel = (self.modal_selected_idx == b_idx) or is_b_hov
            self._modal_button_click_map[b_idx] = (cur_x, cur_x + bw - 1)
            b_col = "bright_foreground" if is_b_sel else "foreground"
            sh_col = "accent" if is_b_sel else "muted"
            btn_bg = "soft_hover" if is_b_hov else ("soft_selection" if is_b_sel else "background")

            r0_s = self.theme_engine.style(b_col, "background", "┌" + ("─" * len(b_lbl)) + "┐", bold=is_b_sel)
            r1_s = (
                self.theme_engine.style(sh_col, "background", "┃", bold=True)
                + self.theme_engine.style("bright_foreground" if is_b_sel else "foreground", btn_bg, b_lbl, bold=is_b_sel)
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
        overlay.append(f"\033[{start_y + 12};{start_x}H" + self.theme_engine.style("accent", "background", bot_line, bold=True))
        return overlay

    def _render_input_modal(self, cols: int, rows: int) -> List[str]:
        """Renderiza la ventana modal interactiva para entrada de Color Hex."""
        title = " EDITAR COLOR HEX DEL TEMA OMARCHY "
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

        selector_line = f"  Propiedad (↑/↓ o clic): {kind_val}".ljust(inner_mw)[:inner_mw]
        self._modal_kind_click_range = (start_y + 3, start_x + 2, start_x + inner_mw - 2)

        box_w = inner_mw - 6
        shown_txt = (self.modal_input_text + "█")[-box_w:].ljust(box_w)
        input_top = ("  ┌" + ("─" * box_w) + "┐  ").ljust(inner_mw)[:inner_mw]
        input_mid = f"  ┃{shown_txt}│  ".ljust(inner_mw)[:inner_mw]
        input_bot = ("  ┗" + ("━" * box_w) + "┙  ").ljust(inner_mw)[:inner_mw]

        overlay.append(f"\033[{start_y};{start_x}H" + self.theme_engine.style("bright_foreground", "background", top_line, bold=True))
        overlay.append(f"\033[{start_y + 1};{start_x}H" + self.theme_engine.style("bright_foreground", "accent", "┃" + title_centered + "│", bold=True))
        overlay.append(f"\033[{start_y + 2};{start_x}H" + self.theme_engine.style("muted", "background", sep_line))
        overlay.append(f"\033[{start_y + 3};{start_x}H" + self.theme_engine.style("bright_foreground", "soft_selection", "┃" + selector_line + "│", bold=True))
        overlay.append(f"\033[{start_y + 4};{start_x}H" + self.theme_engine.style("muted", "background", "┃" + f"  {prompt_lbl}".ljust(inner_mw)[:inner_mw] + "│"))
        overlay.append(f"\033[{start_y + 5};{start_x}H" + self.theme_engine.style("foreground", "background", "┃" + input_top + "│"))
        overlay.append(f"\033[{start_y + 6};{start_x}H" + self.theme_engine.style("bright_foreground", "background", "┃" + input_mid + "│", bold=True))
        overlay.append(f"\033[{start_y + 7};{start_x}H" + self.theme_engine.style("accent", "background", "┃" + input_bot + "│"))

        modal_btns = [
            (0, " Cancelar "),
            (1, " Aplicar "),
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
            is_b_hov = (self.hover_modal_btn_idx == b_idx)
            is_b_sel = (self.modal_selected_idx == b_idx) or is_b_hov
            self._modal_button_click_map[b_idx] = (cur_x, cur_x + bw - 1)
            b_col = "bright_foreground" if is_b_sel else "foreground"
            sh_col = "accent" if is_b_sel else "muted"
            btn_bg = "soft_hover" if is_b_hov else ("soft_selection" if is_b_sel else "background")

            r0_s = self.theme_engine.style(b_col, "background", "┌" + ("─" * len(b_lbl)) + "┐", bold=is_b_sel)
            r1_s = (
                self.theme_engine.style(sh_col, "background", "┃", bold=True)
                + self.theme_engine.style("bright_foreground" if is_b_sel else "foreground", btn_bg, b_lbl, bold=is_b_sel)
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

    # ==========================
    # LECTURA Y ESCRITURA DE VALORES
    # ==========================

    KEY_TO_SETTING: Dict[str, Tuple[str, Any, Any]] = {
        # General
        "general:gaps_in": ("gaps_in", int, 5),
        "general:gaps_out": ("gaps_out", int, 10),
        "general:border_size": ("border_size", int, 2),
        "general:resize_on_border": ("resize_on_border", bool, False),
        "general:extend_border_grab_area": ("extend_border_grab_area", int, 15),
        "general:hover_icon_on_border": ("hover_icon_on_border", bool, True),
        "general:layout": ("layout", str, "dwindle"),
        "general:allow_tearing": ("allow_tearing", bool, False),
        "general:no_focus_fallback": ("no_focus_fallback", bool, False),
        "general:snap:enabled": ("snap_enabled", bool, False),
        "general:snap:window_gap": ("snap_window_gap", int, 10),
        "general:snap:monitor_gap": ("snap_monitor_gap", int, 10),
        "general:snap:border_overlap": ("snap_border_overlap", bool, False),
        # Decoration
        "decoration:rounding": ("rounding", int, 0),
        "decoration:rounding_power": ("rounding_power", float, 2.0),
        "decoration:active_opacity": ("active_opacity", float, 1.0),
        "decoration:inactive_opacity": ("inactive_opacity", float, 1.0),
        "decoration:fullscreen_opacity": ("fullscreen_opacity", float, 1.0),
        "decoration:dim_inactive": ("dim_inactive", bool, False),
        "decoration:dim_strength": ("dim_strength", float, 0.15),
        "decoration:dim_special": ("dim_special", float, 0.20),
        "decoration:blur:enabled": ("blur_enabled", bool, False),
        "decoration:blur:size": ("blur_size", int, 8),
        "decoration:blur:passes": ("blur_passes", int, 1),
        "decoration:blur:new_optimizations": ("blur_new_optimizations", bool, True),
        "decoration:blur:xray": ("blur_xray", bool, False),
        "decoration:blur:ignore_opacity": ("blur_ignore_opacity", bool, True),
        "decoration:blur:vibrancy": ("blur_vibrancy", float, 0.17),
        "decoration:shadow:enabled": ("shadow_enabled", bool, False),
        "decoration:shadow:range": ("shadow_range", int, 4),
        "decoration:shadow:render_power": ("shadow_render_power", int, 3),
        "decoration:shadow:sharp": ("shadow_sharp", bool, False),
        # Animations
        "animations:enabled": ("animations_enabled", bool, True),
        "animations:workspace_wraparound": ("animations_wraparound", bool, False),
        "animations:preset": ("animation_preset", str, "omarchy"),
        "animations:windows": ("anim_windows", str, "popin 87%"),
        "animations:windows_speed": ("anim_windows_speed", float, 3.8),
        "animations:fade_enabled": ("anim_fade_enabled", bool, True),
        "animations:layers": ("anim_layers", str, "fade"),
        "animations:workspaces_enabled": ("anim_workspaces_enabled", bool, False),
        "animations:workspaces": ("anim_workspaces", str, "slide"),
        "animations:special": ("anim_special", str, "slidevert"),
        # Cursor
        "cursor:size": ("cursor_size", int, 24),
        "cursor:no_hardware_cursors": ("no_hw_cursors", bool, True),
        "cursor:inactive_timeout": ("cursor_timeout", int, 0),
        "cursor:hide_on_key_press": ("cursor_hide_on_key", bool, True),
        "cursor:hide_on_touch": ("cursor_hide_on_touch", bool, True),
        "cursor:warp_on_change_workspace": ("cursor_warp_workspace", int, 1),
        "cursor:zoom_factor": ("cursor_zoom", float, 1.0),
        "cursor:zoom_rigid": ("cursor_zoom_rigid", bool, False),
        # Keybinds & Input
        "input:kb_layout": ("kb_layout", str, "us"),
        "input:repeat_rate": ("repeat_rate", int, 40),
        "input:repeat_delay": ("repeat_delay", int, 250),
        "input:numlock_by_default": ("numlock", bool, True),
        "binds:omarchy_default_bindings": ("omarchy_default_bindings", bool, True),
        "binds:omarchy_preinstalled_bindings": ("omarchy_preinstalled_bindings", bool, True),
        "binds:hide_special": ("binds_hide_special", bool, True),
        "binds:workspace_back_forth": ("binds_workspace_back_forth", bool, False),
        "binds:allow_cycles": ("binds_allow_cycles", bool, False),
        # Devices
        "input:follow_mouse": ("follow_mouse", int, 1),
        "input:mouse_refocus": ("mouse_refocus", bool, True),
        "input:sensitivity": ("sensitivity", float, 0.0),
        "input:accel_profile": ("accel_profile", str, "flat"),
        "input:mouse_natural_scroll": ("mouse_natural_scroll", bool, False),
        "input:left_handed": ("left_handed", bool, False),
        "input:touchpad:natural_scroll": ("natural_scroll", bool, False),
        "input:touchpad:scroll_factor": ("touchpad_scroll_factor", float, 0.4),
        "input:touchpad:clickfinger_behavior": ("clickfinger", bool, True),
        "input:touchpad:tap-to-click": ("tap_to_click", bool, True),
        "input:touchpad:disable_while_typing": ("disable_typing", bool, True),
        "input:touchpad:drag_3fg": ("touchpad_drag_3fg", int, 0),
        "gestures:workspace_swipe": ("workspace_swipe", bool, False),
        # Monitors
        "display:xwayland_zero_scaling": ("xwayland_zero_scaling", bool, True),
        # Workspaces & Misc
        "workspace:count": ("workspace_count", int, 5),
        "workspace:layout_toggle": ("workspace_layout", str, "dwindle"),
        "misc:focus_on_activate": ("misc_focus_on_activate", bool, True),
        "misc:dpms_key": ("misc_dpms_key", bool, True),
        "misc:dpms_mouse": ("misc_dpms_mouse", bool, True),
        "misc:focus_under_fs": ("misc_focus_under_fs", int, 1),
        "misc:animate_resizes": ("misc_animate_resizes", bool, False),
        "misc:animate_dragging": ("misc_animate_dragging", bool, False),
        # Layouts
        "dwindle:force_split": ("dwindle_force_split", int, 2),
        "dwindle:preserve_split": ("dwindle_preserve_split", bool, True),
        "dwindle:smart_split": ("dwindle_smart_split", bool, False),
        "dwindle:smart_resizing": ("dwindle_smart_resizing", bool, True),
        "dwindle:split_ratio": ("dwindle_split_ratio", float, 1.0),
        "layout:single_window_aspect": ("single_window_aspect", str, "0 0"),
        "master:new_status": ("master_new_status", str, "master"),
        "master:mfact": ("master_mfact", float, 0.55),
        "master:orientation": ("master_orientation", str, "left"),
        "scrolling:column_width": ("scrolling_column_width", float, 0.49),
        "group:groupbar:enabled": ("groupbar_enabled", bool, True),
        "group:groupbar:font_size": ("groupbar_font_size", int, 12),
        "group:groupbar:height": ("groupbar_height", int, 22),
        "group:groupbar:gradients": ("groupbar_gradients", bool, True),
        # Rules
        "rules:terminal_scroll": ("rules_terminal_scroll", float, 1.5),
        "rules:browser_opaque": ("rules_browser_opaque", bool, True),
        "rules:media_opaque": ("rules_media_opaque", bool, True),
        "rules:pavucontrol_float": ("rules_pavucontrol_float", bool, True),
        "rules:calculator_float": ("rules_calculator_float", bool, True),
        "rules:pip_float": ("rules_pip_float", bool, True),
        "rules:steam_float": ("rules_steam_float", bool, True),
        "rules:localsend_float": ("rules_localsend_float", bool, True),
        # Barra Superior Omarchy
        "bar:visible": ("bar_visible", bool, True),
        "bar:position": ("bar_position", str, "top"),
        "bar:transparent": ("bar_transparent", bool, False),
        "bar:center_anchor": ("bar_center_anchor", str, "omarchy.clock"),
        "bar:clock_format": ("bar_clock_format", str, "ddd d MMM h:mm AP"),
        "bar:clock_alt_format": ("bar_clock_alt_format", str, "d MMMM 'W'ww yyyy"),
        "bar:idle_screensaver": ("idle_screensaver", int, 150),
        "bar:idle_lock": ("idle_lock", int, 300),
        # Temas Omarchy
        "omarchy:theme_mode": ("omarchy_theme_mode", str, "dark"),
        "omarchy:theme_accent": ("omarchy_theme_accent", str, "#E31B23"),
        "omarchy:theme_bg": ("omarchy_theme_bg", str, "#08080B"),
        "omarchy:theme_fg": ("omarchy_theme_fg", str, "#d8d8d8"),
        "omarchy:theme_sel": ("omarchy_theme_sel", str, "#45475a"),
        "omarchy:icons": ("omarchy_icons", str, "Adwaita"),
    }

    def _get_item_value(self, item: SectionItem) -> Any:
        """Obtiene el valor actual de la variable en memoria."""
        key = item.key

        if key.startswith("autostart:item:"):
            idx = int(key.split(":")[-1])
            if 0 <= idx < len(self.autostart_items):
                return bool(self.autostart_items[idx].get("enabled", False))
            return False

        if key.startswith("bar_widget:"):
            s_key = key.split(":", 1)[1]
            return self.settings.get(s_key, "off")

        if key == "omarchy:theme":
            return self.settings.get("omarchy_theme_name", self.theme_engine.current_theme)

        if key == "cursor:size":
            return str(self.settings.get("cursor_size", 24))

        if key == "input:kb_variant":
            v = str(self.settings.get("kb_variant", "")).strip()
            return v if v else "none"

        if key == "input:compose_key":
            return "Alt Gr (Compose)" if self.settings.get("compose_key", "ralt") == "ralt" else "Bloq Mayús (Compose)"

        if key == "display:scale":
            sc = float(self.settings.get("monitor_scale", 1.0))
            return f"{int(sc)}x" if sc.is_integer() else f"{sc}x"

        if key == "display:mode":
            return str(self.settings.get("monitor_mode", "1920x1080@60.00Hz"))

        if key == "display:transform":
            t = int(self.settings.get("monitor_transform", 0))
            labels = {0: "0 (Normal)", 1: "1 (90 grados)", 2: "2 (180 grados)", 3: "3 (270 grados)"}
            return labels.get(t, "0 (Normal)")

        if key == "display:gdk_scale":
            return str(self.settings.get("monitor_gdk_scale", 1))

        if key == "display:vrr":
            v = int(self.settings.get("monitor_vrr", 0))
            labels = {0: "0 (Desactivado)", 1: "1 (Siempre activo)", 2: "2 (Solo pantalla completa)"}
            return labels.get(v, "0 (Desactivado)")

        if key in self.KEY_TO_SETTING:
            s_key, _, def_val = self.KEY_TO_SETTING[key]
            return self.settings.get(s_key, def_val)

        return self.settings.get(key, "-")

    def has_unsaved_changes(self) -> bool:
        """Indica si el usuario modificó algún ajuste o entrada de autostart respecto al último estado aplicado."""
        return (self.settings != self.saved_settings) or (self.autostart_items != self.saved_autostart)

    def _request_section_change(self, target_idx: int, focus_content: bool = False) -> None:
        """
        Cambia a la sección 'target_idx' de la barra lateral izquierda.
        Si existen cambios sin aplicar en la sección actual, abre la ventana modal de confirmación.
        """
        self.dropdown_open = False
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

    def _select_autostart_dropdown_app(self, app_idx: int) -> None:
        """Selecciona una aplicación de la lista desplegable en el modal de Autostart."""
        if self.modal_input_kind != "launch":
            return
        filtered = self._get_filtered_autostart_apps()
        if 0 <= app_idx < len(filtered):
            chosen = filtered[app_idx]
            self.autostart_app_idx = app_idx
            self.autostart_selected_app_name = chosen["name"]
            self.modal_input_text = chosen["cmd"]
            self.autostart_dropdown_open = False
            self.modal_selected_idx = 1

    def _execute_modal_choice(self, choice_idx: int) -> None:
        """Ejecuta la acción seleccionada dentro de la ventana modal activa."""
        state = self.modal_state
        self.modal_state = None
        self.hover_modal_btn_idx = None
        self.hover_autostart_app_idx = None
        self.autostart_dropdown_open = False

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
                chosen_cmd = self.modal_input_text.strip()
                chosen_name = self.autostart_selected_app_name or chosen_cmd

                if self.modal_input_kind == "launch" and not chosen_cmd:
                    filtered = self._get_filtered_autostart_apps()
                    if filtered and 0 <= self.autostart_app_idx < len(filtered):
                        chosen_app = filtered[self.autostart_app_idx]
                        chosen_cmd = chosen_app["cmd"].strip()
                        chosen_name = chosen_app["name"].strip()

                if chosen_cmd:
                    self.autostart_items.append({
                        "cmd": chosen_cmd,
                        "kind": self.modal_input_kind,
                        "enabled": True,
                    })
                    self._sync_autostart_into_settings()
                    self.config_sync.save_autostart_items(self.autostart_items)
                    self.saved_autostart = [dict(x) for x in self.autostart_items]
                    self.saved_settings = dict(self.settings)
                    self.section_items["autostart"] = self._build_autostart_section_items()
                    self.status_message = f"✓ Agregado a autostart.lua: {chosen_name} ({chosen_cmd})"
                else:
                    self.status_message = "Entrada vacia cancelada."
            else:
                self.status_message = "Agregar a autostart cancelado."
            self.modal_input_text = ""
            self.autostart_selected_app_name = ""

        elif state == "create_theme":
            if choice_idx == 1:
                new_name = self.modal_input_text.strip()
                if new_name:
                    self.status_message = f"Creando tema Omarchy '{new_name}'..."
                    self.render()
                    ok, msg = self.theme_engine.create_theme(
                        new_name=new_name,
                        base_theme=self.modal_base_theme,
                        mode=self.modal_theme_mode,
                        activate=True,
                    )
                    self._sync_theme_into_settings()
                    self.saved_settings = dict(self.settings)
                    self.available_themes = self.theme_engine.list_available_themes()
                    self.section_items = self._init_section_items()
                    self.status_message = msg
                else:
                    self.status_message = "Debes escribir un nombre para el nuevo tema."
            else:
                self.status_message = "Creacion de tema cancelada."
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

    def _move_content_selection(self, delta: int) -> None:
        """Mueve la selección vertical en el panel derecho saltando encabezados ('header')."""
        sec_id = self.SECTIONS[self.current_section_idx][1]
        items = self.section_items.get(sec_id, [])
        if not items:
            return
        idx = self.selected_item_idx + delta
        while 0 <= idx < len(items) and items[idx].item_type == "header":
            idx += (1 if delta >= 0 else -1)
        if idx < 0:
            self.selected_item_idx = 0
        elif idx >= len(items):
            self.active_pane = "buttons"
            self.selected_button_idx = 2
        else:
            self.selected_item_idx = idx

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
        self.hover_autostart_app_idx = None
        self.hover_dropdown_idx = None

        # 1. Si hay un menú desplegable (dropdown) abierto en el panel principal
        if self.dropdown_open and not self.modal_state:
            if ch == b"\x1b" and len(ch) == 1:
                self.dropdown_open = False
                return
            if ch == b"\x1b[A":  # Arriba
                self.dropdown_idx = max(0, self.dropdown_idx - 1)
                return
            if ch == b"\x1b[B":  # Abajo
                self.dropdown_idx = min(len(self.dropdown_options) - 1, self.dropdown_idx + 1)
                return
            if ch in (b"\r", b"\n", b" "):
                if self.dropdown_item and 0 <= self.dropdown_idx < len(self.dropdown_options):
                    chosen = self.dropdown_options[self.dropdown_idx]
                    self._set_item_value(self.dropdown_item.key, chosen)
                    self._apply_hyprctl_live(self.dropdown_item.key, chosen)
                self.dropdown_open = False
                return
            return

        # 2. Si hay una ventana modal interactiva activa (input_autostart, create_theme o input_theme_hex)
        if self.modal_state in ("input_autostart", "create_theme", "input_theme_hex"):
            if ch == b"\x1b" and len(ch) == 1:
                if self.modal_state == "input_autostart" and self.autostart_dropdown_open:
                    self.autostart_dropdown_open = False
                    return
                self.modal_state = None
                self.modal_input_text = ""
                self.autostart_dropdown_open = False
                return

            if self.modal_state == "input_autostart":
                if ch == b"\t":  # Tab alterna el tipo (launch / exec)
                    self._cycle_input_modal_kind()
                    return
                if self.modal_input_kind == "launch":
                    filtered = self._get_filtered_autostart_apps()
                    if ch == b"\x1b[A":  # Flecha Arriba
                        if self.autostart_dropdown_open:
                            self.autostart_app_idx = max(0, self.autostart_app_idx - 1)
                        else:
                            self.autostart_dropdown_open = True
                        return
                    if ch == b"\x1b[B":  # Flecha Abajo abre o navega el selector desplegable
                        if not self.autostart_dropdown_open:
                            self.autostart_dropdown_open = True
                        elif filtered:
                            self.autostart_app_idx = min(len(filtered) - 1, self.autostart_app_idx + 1)
                        return
                    if ch in (b"\r", b"\n") and self.autostart_dropdown_open:
                        self._select_autostart_dropdown_app(self.autostart_app_idx)
                        return
            else:
                if ch in (b"\x1b[A", b"\x1b[B"):  # Arriba / Abajo cambia plantilla o propiedad
                    self._cycle_input_modal_kind()
                    return
                if ch == b"\t" and self.modal_state == "create_theme":
                    self.modal_theme_mode = "light" if self.modal_theme_mode == "dark" else "dark"
                    return

            if ch in (b"\x1b[D", b"\x1b[Z"):
                self.modal_selected_idx = max(0, self.modal_selected_idx - 1)
                return
            if ch == b"\x1b[C":
                self.modal_selected_idx = min(1, self.modal_selected_idx + 1)
                return
            if ch in (b"\r", b"\n"):
                self._execute_modal_choice(self.modal_selected_idx)
                return
            if ch in (b"\x7f", b"\x08"):  # Backspace
                self.modal_input_text = self.modal_input_text[:-1]
                self.autostart_selected_app_name = ""
                self.autostart_app_idx = 0
                self.autostart_app_scroll = 0
                return
            # Caracteres imprimibles
            try:
                decoded = ch.decode("utf-8", errors="ignore")
                for c in decoded:
                    if c.isprintable() and c not in ("\r", "\n", "\t"):
                        self.modal_input_text += c
                        self.autostart_selected_app_name = ""
                        self.autostart_app_idx = 0
                        self.autostart_app_scroll = 0
                        if self.modal_state == "input_autostart" and self.modal_input_kind == "launch":
                            self.autostart_dropdown_open = True
            except Exception:
                pass
            return

        # 3. Si hay una ventana modal de confirmación activa
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

        # Eliminar entrada de autostart o tema personalizado con Supr / Delete (\x1b[3~) o 'x'
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
            elif sec_id == "themes":
                items = self.section_items.get("themes", [])
                if 0 <= self.selected_item_idx < len(items):
                    cur_item = items[self.selected_item_idx]
                    if cur_item.key.startswith("user_theme:item:"):
                        t_slug = cur_item.key.split(":", 2)[-1]
                        ok, msg = self.theme_engine.delete_user_theme(t_slug)
                        self._sync_theme_into_settings()
                        self.saved_settings = dict(self.settings)
                        self.section_items = self._init_section_items()
                        self.selected_item_idx = max(0, min(self.selected_item_idx, len(self.section_items["themes"]) - 1))
                        self.status_message = msg
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
                self._move_content_selection(-1)
            return

        if ch == b"\x1b[B":  # Flecha Abajo
            if self.active_pane == "sidebar":
                self._request_section_change(self.current_section_idx + 1, focus_content=False)
            elif self.active_pane == "content":
                self._move_content_selection(1)
            return

        # Enter o Espacio para activar/conmutar/abrir desplegable
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
        """Alterna el selector de tipo o plantilla en los modales de entrada de texto."""
        if self.modal_state == "input_autostart":
            self.modal_input_kind = "exec" if self.modal_input_kind == "launch" else "launch"
            if self.modal_input_kind == "exec":
                self.autostart_dropdown_open = False
                self.autostart_selected_app_name = ""
        elif self.modal_state == "create_theme":
            themes = self.available_themes if self.available_themes else ["tokyo-night", "catppuccin", "lizarbe"]
            try:
                idx = (themes.index(self.modal_base_theme) + 1) % len(themes)
            except ValueError:
                idx = 0
            self.modal_base_theme = themes[idx]
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
        cols, rows = shutil.get_terminal_size((84, 42))
        sidebar_w = self._get_sidebar_width(cols)

        # 1. Si hay un menú desplegable (dropdown) abierto en el panel principal
        if self.dropdown_open and not self.modal_state:
            dy1, dy2, dx1, dx2 = self._dropdown_box_bounds
            if act == b"M" and btn == 35:
                if dy1 <= y <= dy2 and dx1 <= x <= dx2 and y in self._dropdown_row_map:
                    self.hover_dropdown_idx = self._dropdown_row_map[y]
                    self.dropdown_idx = self.hover_dropdown_idx
                else:
                    self.hover_dropdown_idx = None
                return
            if act == b"M" and btn in (64, 65):
                if btn == 64:
                    self.dropdown_idx = max(0, self.dropdown_idx - 1)
                else:
                    self.dropdown_idx = min(len(self.dropdown_options) - 1, self.dropdown_idx + 1)
                return
            if act == b"M" and btn == 0:
                if dy1 <= y <= dy2 and dx1 <= x <= dx2 and y in self._dropdown_row_map:
                    opt_idx = self._dropdown_row_map[y]
                    if self.dropdown_item and 0 <= opt_idx < len(self.dropdown_options):
                        chosen = self.dropdown_options[opt_idx]
                        self._set_item_value(self.dropdown_item.key, chosen)
                        self._apply_hyprctl_live(self.dropdown_item.key, chosen)
                self.dropdown_open = False
                return
            return

        # 2. Si hay una ventana modal abierta, dirigir clics, rueda y hover al modal
        if self.modal_state:
            if act == b"M" and btn == 35:
                m_ymin, m_ymax = self._modal_button_row_range
                self.hover_modal_btn_idx = None
                self.hover_autostart_app_idx = None
                if self.modal_state == "input_autostart" and self.modal_input_kind == "launch" and self.autostart_dropdown_open:
                    lx_min, lx_max = self._autostart_list_x_range
                    if y in self._autostart_list_click_map and lx_min <= x <= lx_max:
                        self.hover_autostart_app_idx = self._autostart_list_click_map[y]
                        return
                if m_ymin <= y <= m_ymax:
                    for b_idx, (bx_min, bx_max) in self._modal_button_click_map.items():
                        if bx_min <= x <= bx_max:
                            self.modal_selected_idx = b_idx
                            self.hover_modal_btn_idx = b_idx
                            return
                return

            if act == b"M" and btn in (64, 65) and self.modal_state == "input_autostart":
                if self.modal_input_kind == "launch" and self.autostart_dropdown_open:
                    filtered = self._get_filtered_autostart_apps()
                    if filtered:
                        if btn == 64:
                            self.autostart_app_idx = max(0, self.autostart_app_idx - 1)
                        else:
                            self.autostart_app_idx = min(len(filtered) - 1, self.autostart_app_idx + 1)
                return

            if act == b"M" and btn == 0:
                ky, kxmin, kxmax = self._modal_kind_click_range
                if y == ky and kxmin <= x <= kxmax:
                    self._cycle_input_modal_kind()
                    return
                if self.modal_state == "create_theme":
                    my, mxmin, mxmax = self._modal_mode_click_range
                    if y == my and mxmin <= x <= mxmax:
                        self.modal_theme_mode = "light" if self.modal_theme_mode == "dark" else "dark"
                        return
                if self.modal_state == "input_autostart":
                    # Clic sobre el botón del selector desplegable (solo funciona en modo 'launch')
                    ddy1, ddy2, ddx1, ddx2 = self._autostart_dropdown_btn_range
                    if self.modal_input_kind == "launch" and ddy1 <= y <= ddy2 and ddx1 <= x <= ddx2:
                        self.autostart_dropdown_open = not self.autostart_dropdown_open
                        return
                    # Clic sobre una aplicación dentro de la lista desplegable abierta
                    if self.modal_input_kind == "launch" and self.autostart_dropdown_open:
                        lx_min, lx_max = self._autostart_list_x_range
                        if y in self._autostart_list_click_map and lx_min <= x <= lx_max:
                            clicked_idx = self._autostart_list_click_map[y]
                            self._select_autostart_dropdown_app(clicked_idx)
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
                        elif item.item_type in ("toggle", "select", "action", "theme_card"):
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
                if y == 1:
                    if x >= cols - 15:
                        self.running = False
                    return

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

                if y == rows:
                    if x > cols - 15:
                        self.running = False
                    elif x <= 16:
                        if self.active_pane == "sidebar":
                            self.active_pane = "content"
                        elif self.active_pane == "content":
                            self.active_pane = "buttons"
                        else:
                            self.active_pane = "sidebar"
                    return

                if x <= sidebar_w:
                    sec_idx = self._sidebar_click_map.get(y)
                    if sec_idx is not None:
                        self._request_section_change(sec_idx, focus_content=True)
                    return

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
                            c_start, _ = info["control_range"]
                            self._open_dropdown_for_item(item, anchor_y=info.get("row_y", y), anchor_x=c_start)

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

                        elif item.item_type == "theme_card":
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
                        self._move_content_selection(-1)

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
                        self._move_content_selection(1)

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
        """Ejecuta la acción, abre el menú desplegable (en 'select') o conmuta el toggle del elemento seleccionado."""
        sec_id = self.SECTIONS[self.current_section_idx][1]
        items = self.section_items.get(sec_id, [])
        if not items or self.selected_item_idx >= len(items):
            return

        item = items[self.selected_item_idx]

        if item.item_type == "toggle":
            self._adjust_current_item(delta=1)
        elif item.item_type == "select":
            # Abrir menú desplegable en la fila correspondiente
            row_y = 5 + (self.selected_item_idx - self.content_scroll_offset) * 3
            self._open_dropdown_for_item(item, anchor_y=row_y, anchor_x=45)
        elif item.item_type in ("action", "theme_card"):
            self._execute_action(item.key)

    def _set_item_value(self, key: str, val: Any) -> None:
        """Guarda el valor en la estructura de ajustes en memoria."""
        if key.startswith("autostart:item:"):
            idx = int(key.split(":")[-1])
            if 0 <= idx < len(self.autostart_items):
                self.autostart_items[idx]["enabled"] = bool(val)
                self._sync_autostart_into_settings()
            return

        if key.startswith("bar_widget:"):
            s_key = key.split(":", 1)[1]
            self.settings[s_key] = str(val)
            self.config_sync.save_bar_settings(self.settings, reload_shell=True)
            self.status_message = f"✓ Widget actualizado a '{val}' en la barra superior."
            return

        if key == "input:kb_variant":
            self.settings["kb_variant"] = "" if str(val) == "none" else str(val)
            return

        if key == "input:compose_key":
            self.settings["compose_key"] = "ralt" if "Alt Gr" in str(val) else "caps"
            return

        if key == "display:scale":
            scale_float = float(str(val).replace("x", ""))
            if self.monitors:
                self.monitors[0]["scale"] = scale_float
            self.settings["monitor_scale"] = scale_float
            return

        if key == "display:mode":
            self.settings["monitor_mode"] = str(val)
            return

        if key == "display:transform":
            first_ch = str(val).strip()[0]
            self.settings["monitor_transform"] = int(first_ch) if first_ch.isdigit() else 0
            return

        if key == "display:gdk_scale":
            self.settings["monitor_gdk_scale"] = int(val)
            return

        if key == "display:vrr":
            first_ch = str(val).strip()[0]
            self.settings["monitor_vrr"] = int(first_ch) if first_ch.isdigit() else 0
            return

        if key == "omarchy:theme":
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
            return

        if key in self.KEY_TO_SETTING:
            s_key, caster, _ = self.KEY_TO_SETTING[key]
            self.settings[s_key] = caster(val)

            # Si es una propiedad de la barra superior, aplicar en vivo sobre shell.json
            if key.startswith("bar:"):
                self.config_sync.save_bar_settings(self.settings, reload_shell=True)
                self.status_message = "✓ Configuracion de la barra superior actualizada."
                return

            # Previsualizar en vivo el cambio de color en el motor TUI
            if key == "omarchy:theme_accent":
                self.theme_engine._colors["accent"] = str(val)
                self.theme_engine.update_derived_colors()
            elif key == "omarchy:theme_bg":
                self.theme_engine._colors["background"] = str(val)
                self.theme_engine.update_derived_colors()
            elif key == "omarchy:theme_fg":
                self.theme_engine._colors["foreground"] = str(val)
                self.theme_engine._colors["bright_foreground"] = str(val)
                self.theme_engine.update_derived_colors()
            elif key == "omarchy:theme_sel":
                self.theme_engine._colors["selection"] = str(val)
                self.theme_engine.update_derived_colors()
        else:
            self.settings[key] = val

    def _apply_hyprctl_live(self, key: str, val: Any) -> None:
        """Aplica la variable en caliente a Hyprland si corresponde."""
        direct_hypr_keys = {
            "general:gaps_in",
            "general:gaps_out",
            "general:border_size",
            "general:resize_on_border",
            "general:extend_border_grab_area",
            "general:hover_icon_on_border",
            "general:layout",
            "general:allow_tearing",
            "general:no_focus_fallback",
            "general:snap:enabled",
            "general:snap:window_gap",
            "general:snap:monitor_gap",
            "general:snap:border_overlap",
            "decoration:rounding",
            "decoration:rounding_power",
            "decoration:active_opacity",
            "decoration:inactive_opacity",
            "decoration:fullscreen_opacity",
            "decoration:dim_inactive",
            "decoration:dim_strength",
            "decoration:dim_special",
            "decoration:blur:enabled",
            "decoration:blur:size",
            "decoration:blur:passes",
            "decoration:blur:new_optimizations",
            "decoration:blur:xray",
            "decoration:blur:ignore_opacity",
            "decoration:blur:vibrancy",
            "decoration:shadow:enabled",
            "decoration:shadow:range",
            "decoration:shadow:render_power",
            "decoration:shadow:sharp",
            "animations:enabled",
            "animations:workspace_wraparound",
            "cursor:no_hardware_cursors",
            "cursor:inactive_timeout",
            "cursor:hide_on_key_press",
            "cursor:hide_on_touch",
            "cursor:warp_on_change_workspace",
            "cursor:zoom_factor",
            "cursor:zoom_rigid",
            "input:kb_layout",
            "input:repeat_rate",
            "input:repeat_delay",
            "input:numlock_by_default",
            "input:follow_mouse",
            "input:mouse_refocus",
            "input:sensitivity",
            "input:accel_profile",
            "input:left_handed",
            "input:touchpad:natural_scroll",
            "input:touchpad:scroll_factor",
            "input:touchpad:clickfinger_behavior",
            "input:touchpad:tap-to-click",
            "input:touchpad:disable_while_typing",
            "input:touchpad:drag_3fg",
            "dwindle:force_split",
            "dwindle:preserve_split",
            "dwindle:smart_split",
            "dwindle:smart_resizing",
            "dwindle:default_split_ratio",
            "master:new_status",
            "master:mfact",
            "master:orientation",
            "scrolling:column_width",
            "group:groupbar:enabled",
            "group:groupbar:font_size",
            "group:groupbar:height",
            "group:groupbar:gradients",
        }
        mapped_keys = {
            "binds:hide_special": "binds:hide_special_on_workspace_change",
            "binds:workspace_back_forth": "binds:workspace_back_and_forth",
            "binds:allow_cycles": "binds:allow_workspace_cycles",
            "input:mouse_natural_scroll": "input:natural_scroll",
            "misc:focus_on_activate": "misc:focus_on_activate",
            "misc:dpms_key": "misc:key_press_enables_dpms",
            "misc:dpms_mouse": "misc:mouse_move_enables_dpms",
            "misc:focus_under_fs": "misc:on_focus_under_fullscreen",
            "misc:animate_resizes": "misc:animate_manual_resizes",
            "misc:animate_dragging": "misc:animate_mouse_windowdragging",
            "dwindle:split_ratio": "dwindle:default_split_ratio",
            "display:xwayland_zero_scaling": "xwayland:force_zero_scaling",
        }
        if key in direct_hypr_keys:
            HyprIPC.set_keyword(key, val)
        elif key in mapped_keys:
            HyprIPC.set_keyword(mapped_keys[key], val)
        elif key == "input:kb_variant":
            HyprIPC.set_keyword("input:kb_variant", "" if str(val) == "none" else str(val))
        elif key == "display:vrr":
            first_ch = str(val).strip()[0]
            if first_ch.isdigit():
                HyprIPC.set_keyword("misc:vrr", int(first_ch))

    def _execute_action(self, action_key: str) -> None:
        """Ejecuta acciones especiales como modales de autostart, creación/gestión de temas Omarchy o utilidades."""
        if action_key == "action:add_autostart":
            self.installed_apps = self.config_sync.list_installed_applications()
            self.modal_state = "input_autostart"
            self.modal_input_text = ""
            self.modal_input_kind = "launch"
            self.autostart_dropdown_open = False
            self.autostart_selected_app_name = ""
            self.autostart_app_idx = 0
            self.autostart_app_scroll = 0
            self.modal_selected_idx = 1
            return

        elif action_key == "action:create_theme":
            self.modal_state = "create_theme"
            self.modal_base_theme = self.theme_engine.current_theme
            self.modal_theme_mode = self.theme_engine.mode
            self.modal_input_text = ""
            self.modal_selected_idx = 1
            return

        elif action_key == "action:clone_theme":
            self.modal_state = "create_theme"
            self.modal_base_theme = self.theme_engine.current_theme
            self.modal_theme_mode = self.theme_engine.mode
            self.modal_input_text = f"{self.theme_engine.current_theme}-custom"
            self.modal_selected_idx = 1
            return

        elif action_key.startswith("user_theme:item:"):
            target_slug = action_key.split(":", 2)[-1]
            self._set_item_value("omarchy:theme", target_slug)
            return

        elif action_key == "action:custom_theme_hex":
            self.modal_state = "input_theme_hex"
            self.modal_hex_target = "accent"
            self.modal_input_text = str(self.settings.get("omarchy_theme_accent", "#E31B23"))
            self.modal_selected_idx = 1
            return

        elif action_key == "action:reset_bar_defaults":
            if self.config_sync.reset_bar_defaults(self.settings):
                self.saved_settings = dict(self.settings)
                self.section_items["bar"] = self._build_bar_section_items()
                self.status_message = "✓ Barra superior restaurada al diseño predeterminado de Omarchy."
            else:
                self.status_message = "Error al restaurar la barra superior."
            return

        elif action_key == "action:restart_shell":
            try:
                subprocess.Popen(
                    ["omarchy-restart-shell"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.status_message = "✓ Reiniciando shell y barra superior de Omarchy..."
            except Exception:
                self.status_message = "No se encontró 'omarchy-restart-shell'."
            return

        elif action_key == "action:fix_caps":
            use_ralt = (self.settings.get("compose_key", "ralt") == "ralt")
            self.config_sync.fix_caps_lock(use_ralt=use_ralt)
            self.saved_settings["compose_key"] = self.settings.get("compose_key", "ralt")
            self.status_message = "✓ Tecla Bloq Mayus configurada y guardada en input.lua."

        elif action_key == "action:save_monitor":
            m_name = self.monitors[0].get("name", "") if self.monitors else ""
            mode = str(self.settings.get("monitor_mode", "1920x1080@60.00Hz"))
            if mode == "preferred":
                res, hz = "preferred", 60.0
            else:
                res = mode.split("@")[0] if "@" in mode else "1920x1080"
                hz_str = mode.split("@")[1].replace("Hz", "") if "@" in mode else "60"
                try:
                    hz = float(hz_str)
                except ValueError:
                    hz = 60.0
            sc = float(self.settings.get("monitor_scale", 1.0))
            tr = int(self.settings.get("monitor_transform", 0))
            gdk = int(self.settings.get("monitor_gdk_scale", 1))
            if self.config_sync.save_monitor_config(m_name, res, hz, sc, transform=tr, gdk_scale=gdk):
                self.saved_settings["monitor_mode"] = mode
                self.saved_settings["monitor_scale"] = sc
                self.saved_settings["monitor_transform"] = tr
                self.saved_settings["monitor_gdk_scale"] = gdk
                self.status_message = f"✓ Monitor {m_name} ({mode}, {sc}x) guardado en monitors.lua."
            else:
                self.status_message = "Error al guardar monitors.lua."

        elif action_key == "action:next_wallpaper":
            try:
                subprocess.Popen(
                    ["omarchy-theme-bg-next"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.status_message = "✓ Fondo de pantalla de Omarchy cambiado."
            except Exception:
                self.status_message = "No se encontró el comando 'omarchy-theme-bg-next'."

        elif action_key == "action:toggle_bar":
            try:
                subprocess.Popen(
                    ["omarchy-toggle-bar"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.settings["bar_visible"] = not bool(self.settings.get("bar_visible", True))
                self.saved_settings["bar_visible"] = self.settings["bar_visible"]
                self.status_message = "✓ Visibilidad de la barra superior de Omarchy alternada."
            except Exception:
                self.status_message = "No se encontró el comando 'omarchy-toggle-bar'."

        elif action_key == "action:toggle_nightlight":
            try:
                subprocess.Popen(
                    ["omarchy-toggle-nightlight"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.status_message = "✓ Filtro de luz nocturna (hyprsunset) alternado."
            except Exception:
                self.status_message = "No se encontró el comando 'omarchy-toggle-nightlight'."

        elif action_key == "action:apply_lizarbe_full":
            self.status_message = "Aplicando configuración Lizarbe..."
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
        """Aplica y guarda todas las opciones en hyprland-gui.lua, autostart.lua, shell.json y tema Omarchy."""
        ok_gui = self.config_sync.save_gui_settings(self.settings, apply_live=True)
        ok_auto = self.config_sync.save_autostart_items(self.autostart_items)

        if self.settings.get("compose_key") != self.saved_settings.get("compose_key"):
            self.config_sync.fix_caps_lock(use_ralt=(self.settings.get("compose_key", "ralt") == "ralt"))

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
            self.status_message = "✓ Cambios aplicados en Hyprland, Barra Superior y Omarchy."
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
        defaults = self.config_sync.get_default_settings()
        self.settings.update(defaults)
        self._sync_theme_into_settings()
        self._sync_autostart_into_settings()
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
