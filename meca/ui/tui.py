"""
Interfaz TUI Monolítica para Meca HyprConfig (Estilo HyprMod / GNOME / macOS).
Arquitectura de 2 paneles (Categorías a la izquierda, Variables de Hyprland y Omarchy a la derecha),
con soporte completo de ratón, menús desplegables, tarjetas de temas, controles en cuadrados cerrados,
modales interactivos, gestión de Autostart, Barra Superior y edición de temas de Omarchy.
"""

from __future__ import annotations
import json
import os
import re
import sys
import tty
import termios
import select
import shutil
import subprocess
import time
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
        ("LOOK & FEEL", "general", "", "General", "Espaciado, bordes y layout"),
        ("LOOK & FEEL", "decoration", "", "Decoration", "Redondeo, opacidad, blur y sombras"),
        ("LOOK & FEEL", "animations", "", "Animations", "Velocidad y estilo de animaciones"),
        ("LOOK & FEEL", "cursor", "󰍽", "Cursor", "Tema, tamaño, ocultacion y zoom"),
        ("INPUT", "keybinds", "", "Keybinds", "Atajos de teclado del sistema"),
        ("INPUT", "devices", "󰍽", "Input", "Teclado, raton y touchpad"),
        ("DISPLAY", "monitors", "󰍹", "Monitors", "Escala, resolucion y rotacion"),
        ("DISPLAY", "workspaces", "󰕰", "Workspaces", "Escritorios y foco"),
        ("WINDOW MANAGEMENT", "layouts", "󰕮", "Layouts", "Dwindle, Master, Scrolling y grupos"),
        ("WINDOW MANAGEMENT", "rules", "", "Window Rules", "Ventanas flotantes y opacidad"),
        ("STARTUP & EXTRAS", "autostart", "", "Autostart", "Inicio automatico de sesion"),
        ("STARTUP & EXTRAS", "bar", "󰍜", "Barra Superior", "Posicion, reloj y widgets"),
        ("STARTUP & EXTRAS", "themes", "󰏘", "Temas Omarchy", "Seleccion, edicion y creacion"),
        ("STARTUP & EXTRAS", "omarchy", "󰚰", "Omarchy", "Fondo, barra y luz nocturna"),
    ]

    # Categorías de la ventana dedicada de Creación/Edición de Temas Omarchy
    CREATOR_SECTIONS = [
        ("ESTUDIO TEMA", "creator_identity", "󰏘", "Identidad", "Nombre, base, modo e iconos"),
        ("ESTUDIO TEMA", "creator_borders", "", "Bordes y Acento", "Acento y bordes de ventana"),
        ("ESTUDIO TEMA", "creator_widgets", "󰍜", "Widgets", "Fondo, texto, borde y opacidad"),
        ("ESTUDIO TEMA", "creator_media", "󰸉", "Fondos y Preview", "Fondos de pantalla y vista previa"),
        ("ESTUDIO TEMA", "creator_terminal", "", "Terminal", "Fondo, texto y paleta ANSI"),
        ("ESTUDIO TEMA", "creator_extras", "", "Extras", "Neovim y teclado RGB"),
    ]

    # Paleta curada de colores Hex para selección rápida con previsualización
    CURATED_HEX_PALETTE = [
        "#E31B23", "#7aa2f7", "#89b4fa", "#1e66f5", "#2DB872", "#9ece6a",
        "#E5A83B", "#e0af68", "#f38ba8", "#f7768e", "#ad8ee6", "#cba6f7",
        "#45A0B5", "#94e2d5", "#8bc9eb", "#eb927b", "#08080B", "#1a1b26",
        "#1e1e2e", "#101315", "#16242d", "#1f1d24", "#24283b", "#292e42",
        "#313244", "#414868", "#45475a", "#585b70", "#d8d8d8", "#a9b1d6",
        "#cdd6f4", "#ececec", "#ffffff", "#eff1f5", "#000000", "#1c1c1c",
    ]

    # Codepoints de teclas modificadoras (protocolo Kitty y keysyms Wayland/X11)
    KITTY_MOD_MAP = {
        57441: "SHIFT", 57447: "SHIFT", 65505: "SHIFT", 65506: "SHIFT",
        57442: "CTRL",  57448: "CTRL",  65507: "CTRL",  65508: "CTRL",
        57443: "ALT",   57449: "ALT",   65511: "ALT",   65512: "ALT", 65027: "ALT", 57453: "ALT",
        57444: "SUPER", 57450: "SUPER", 65513: "SUPER", 65514: "SUPER", 65515: "SUPER", 65516: "SUPER",
        57445: "SUPER", 57446: "SUPER", 57451: "SUPER", 57452: "SUPER",
    }

    # Mapa de codepoints de teclas especiales no imprimibles
    SPECIAL_CODEPOINTS = {
        13: "RETURN", 32: "SPACE", 27: "ESCAPE", 9: "TAB", 127: "BACKSPACE",
        57376: "F1", 57377: "F2", 57378: "F3", 57379: "F4", 57380: "F5", 57381: "F6",
        57382: "F7", 57383: "F8", 57384: "F9", 57385: "F10", 57386: "F11", 57387: "F12",
        57352: "UP", 57353: "DOWN", 57354: "RIGHT", 57355: "LEFT",
        57356: "PAGE_UP", 57357: "PAGE_DOWN", 57358: "HOME", 57359: "END",
        57360: "INSERT", 57361: "DELETE", 57362: "PRINT",
        65377: "PRINT", 65300: "PRINT", 65385: "PRINT", 65288: "BACKSPACE",
        65289: "TAB", 65293: "RETURN", 65307: "ESCAPE", 65535: "DELETE",
    }

    _normalize_keybind_string = staticmethod(ConfigSync.normalize_keybind_string)

    XKB_KEY_MAP = {
        9: "ESCAPE", 22: "BACKSPACE", 23: "TAB", 36: "RETURN", 65: "SPACE", 66: "CAPS_LOCK",
        37: "CTRL", 105: "CTRL",
        50: "SHIFT", 62: "SHIFT",
        64: "ALT", 108: "ALT",
        133: "SUPER", 134: "SUPER",
        107: "PRINT", 218: "PRINT",
        110: "HOME", 111: "UP", 112: "PAGE_UP", 113: "LEFT",
        114: "RIGHT", 115: "END", 116: "DOWN", 117: "PAGE_DOWN",
        118: "INSERT", 119: "DELETE",
        67: "F1", 68: "F2", 69: "F3", 70: "F4", 71: "F5", 72: "F6",
        73: "F7", 74: "F8", 75: "F9", 76: "F10", 95: "F11", 96: "F12",
        10: "1", 11: "2", 12: "3", 13: "4", 14: "5", 15: "6", 16: "7", 17: "8", 18: "9", 19: "0",
        24: "Q", 25: "W", 26: "E", 27: "R", 28: "T", 29: "Y", 30: "U", 31: "I", 32: "O", 33: "P",
        38: "A", 39: "S", 40: "D", 41: "F", 42: "G", 43: "H", 44: "J", 45: "K", 46: "L",
        52: "Z", 53: "X", 54: "C", 55: "V", 56: "B", 57: "N", 58: "M",
        20: "MINUS", 21: "EQUAL", 34: "BRACKETLEFT", 35: "BRACKETRIGHT",
        47: "SEMICOLON", 48: "APOSTROPHE", 49: "GRAVE", 51: "BACKSLASH",
        59: "comma", 60: "period", 61: "slash",
        121: "XF86AudioMute", 122: "XF86AudioLowerVolume", 123: "XF86AudioRaiseVolume",
        148: "XF86Calculator", 171: "XF86AudioNext", 172: "XF86AudioPlay", 173: "XF86AudioPrev",
        232: "XF86MonBrightnessDown", 233: "XF86MonBrightnessUp",
    }

    COMPOSE_KEY_MAP = {
        66: ("caps", "Bloq Mayús (Caps Lock)"),
        135: ("menu", "Tecla Menú"),
        134: ("rwin", "Super / Win Derecho"),
        133: ("lwin", "Super / Win Izquierdo"),
        107: ("prsc", "Impr Pant (PrtSc)"),
        218: ("prsc", "Impr Pant (PrtSc)"),
        118: ("ins", "Insert"),
        127: ("paus", "Pausa (Pause)"),
        78: ("sclk", "Bloq Despl (Scroll Lock)"),
        105: ("rctrl", "Ctrl Derecho"),
        37: ("lctrl", "Ctrl Izquierdo"),
        108: ("ralt", "Alt Gr (Desactiva @)"),
    }

    @classmethod
    def _init_xkb_key_map(cls) -> Dict[int, str]:
        """Inicializa el mapa de keycodes con base estática y enriquece dinámicamente según la distribución del sistema."""
        table = dict(cls.XKB_KEY_MAP)
        try:
            proc = subprocess.run(["xkbcli", "dump-keymap-wayland"], capture_output=True, text=True, timeout=0.3)
            if proc.returncode == 0:
                name_to_code = {}
                for line in proc.stdout.splitlines():
                    m = re.match(r"^\s*<(\w+)>\s*=\s*(\d+);", line)
                    if m:
                        name_to_code[m.group(1)] = int(m.group(2))
                for line in proc.stdout.splitlines():
                    m = re.search(r"key\s*<(\w+)>\s*\{\s*(?:type=\s*\"[^\"]*\",\s*symbols\[\d+\]=\s*)?\[\s*(\w+)", line)
                    if m:
                        key_name = m.group(1)
                        sym = m.group(2)
                        if key_name in name_to_code:
                            code = name_to_code[key_name]
                            if code not in table and not sym.startswith("U"):
                                table[code] = sym.upper()
        except Exception:
            pass
        return table

    def __init__(self, was_tiled: Optional[bool] = None):
        self.theme_engine = ThemeEngine()
        self.config_sync = ConfigSync()
        self.running = True
        self._frame_count = 0
        self._was_tiled = was_tiled
        self._rec_file = f"/tmp/meca_rec_{os.getuid()}.json"
        self._compose_rec_file = f"/tmp/meca_compose_rec_{os.getuid()}.json"
        self.xkb_key_map = self._init_xkb_key_map()
        self.orig_termios = None  # Inicializado aquí para evitar AttributeError en el bloque finally

        # Modo de ventana activa: "main" (panel principal) | "theme_creator" (ventana de creación/edición de temas)
        self.view_mode: str = "main"
        self._prev_main_section_idx: int = 12
        self.creator_is_editing: bool = False
        self.creator_editing_slug: str = ""
        self.theme_creator_spec: Dict[str, Any] = self.theme_engine.get_theme_full_spec(self.theme_engine.current_theme)

        # Navegación de paneles: "sidebar" (izquierda), "content" (derecha) o "buttons" (barra inferior)
        self.active_pane = "sidebar"
        self.current_section_idx = 0
        self.selected_item_idx = 0
        self.content_scroll_offset = 0
        self.status_message = "Listo."

        # Datos cargados del sistema
        self.settings = self.config_sync.load_gui_settings()
        self.monitors = HyprIPC.get_monitors()
        self.available_themes = self.theme_engine.list_available_themes()
        self.cursor_themes = self.config_sync.list_cursor_themes()
        self.autostart_items = self.config_sync.load_autostart_items()
        self.keybind_items = self.config_sync.load_keybinds()
        self.installed_apps = self.config_sync.list_installed_applications()

        # Aplicar correcciones silenciosas de fondo (hook de actualización y logo fastfetch) sin ensuciar el panel
        self._ensure_background_fixes()

        # Sincronizar propiedades del tema Omarchy, autostart y keybinds dentro de settings
        self._sync_theme_into_settings()
        self._sync_autostart_into_settings()
        self._sync_keybinds_into_settings()

        # Escalas soportadas para monitores
        self.scales = ["1x", "1.25x", "1.5x", "1.75x", "2x"]
        self.scale_values = [1.0, 1.25, 1.5, 1.75, 2.0]

        # Copia de seguridad del estado guardado para detectar cambios pendientes al cambiar de sección
        self.saved_settings = dict(self.settings)
        self.saved_autostart = [dict(x) for x in self.autostart_items]
        self.saved_keybinds = [dict(x) for x in self.keybind_items]
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

        # Estado del menú contextual de clic secundario (clic derecho / tecla m)
        self.context_menu_open: bool = False
        self.context_menu_x: int = 24
        self.context_menu_y: int = 10
        self.context_menu_title: str = ""
        self.context_menu_items: List[Tuple[str, str]] = []  # [(etiqueta, accion_id), ...]
        self.context_menu_idx: int = 0
        self.hover_context_idx: Optional[int] = None
        self._context_row_map: Dict[int, int] = {}
        self._context_box_bounds: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (y1, y2, x1, x2)

        # Estado de ventana modal:
        # None | "confirm_section_change" | "confirm_reset" | "confirm_delete_theme" |
        # "input_autostart" | "input_theme_hex" | "input_creator_text" | "edit_keybind" | "add_keybind"
        self.modal_state: Optional[str] = None
        self.modal_selected_idx: int = 0
        self.modal_target_theme: str = ""
        self.pending_section_idx: Optional[int] = None
        self.pending_focus_content: bool = False
        self._pending_delete_theme_slug: str = ""  # Slug del tema pendiente de borrar
        self._modal_button_click_map: Dict[int, Tuple[int, int]] = {}
        self._modal_button_row_range: Tuple[int, int] = (0, 0)

        # Estado de entrada de texto y selectores para modales interactivos
        self.modal_input_text: str = ""
        self.modal_input_secondary: str = ""
        self.modal_input_tertiary: str = ""
        self.modal_active_field: int = 0  # 0: campo 1, 1: campo 2, 2: campo 3
        self.modal_keybind_idx: int = 0
        self.modal_kb_idx: int = 0
        self.modal_kb_field: int = 0
        self.modal_kb_keys: str = ""
        self.modal_kb_action: str = ""
        self.modal_kb_desc: str = ""
        self.context_menu_target_key: str = ""
        self.modal_input_kind: str = "launch"  # "launch" (App/Servicio) | "exec" (Comando)
        self.modal_hex_target: str = "creator:accent"
        self.modal_text_target: str = "creator:name"
        self.modal_base_theme: str = self.theme_engine.current_theme
        self.modal_theme_mode: str = "dark"
        self._modal_kind_click_range: Tuple[int, int, int] = (0, 0, 0)  # (y, x_min, x_max)
        self._modal_mode_click_range: Tuple[int, int, int] = (0, 0, 0)  # (y, x_min, x_max)
        self._kb_field_click_ranges: Dict[int, Tuple[int, int, int, int]] = {}
        self.modal_kb_recording: bool = False
        self._hypr_rec_active: bool = False
        self._last_recording_finish_time: float = 0.0
        self._kb_held_mods: set[str] = set()
        self._kb_currently_pressed: set[int] = set()
        self._kb_last_combo: str = ""
        self._kb_captured_ready: bool = False
        self._kb_mod_chips: Dict[str, Tuple[int, int, int]] = {}
        self._kb_rec_btn_range: Tuple[int, int, int] = (0, 0, 0)
        self.hover_kb_mod: Optional[str] = None
        self.hover_kb_rec: bool = False

        # Estado de pestañas y selector de aplicaciones para el modal de nuevo atajo
        self.modal_kb_tab: str = "program"  # "program" | "command"
        self.modal_kb_app_extra: str = ""
        self.modal_kb_app_selected_cmd: str = ""
        self.modal_kb_app_selected_name: str = ""
        self.modal_kb_app_idx: int = 0
        self.modal_kb_app_scroll: int = 0
        self.modal_kb_app_search: str = ""
        self.modal_kb_app_dropdown_open: bool = False
        self.hover_kb_app_idx: Optional[int] = None
        self.hover_kb_tab: Optional[str] = None
        self._kb_tab_click_ranges: Dict[str, Tuple[int, int, int]] = {}
        self._kb_app_dropdown_btn_range: Tuple[int, int, int, int] = (0, 0, 0, 0)
        self._kb_app_list_click_map: Dict[int, int] = {}
        self._kb_app_list_x_range: Tuple[int, int] = (0, 0)

        # Estado del selector desplegable de aplicaciones en Autostart
        self.autostart_dropdown_open: bool = False
        self.autostart_selected_app_name: str = ""
        self.autostart_app_idx: int = 0
        self.autostart_app_scroll: int = 0
        self.hover_autostart_app_idx: Optional[int] = None
        self._autostart_dropdown_btn_range: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (y1, y2, x1, x2)
        self._autostart_list_click_map: Dict[int, int] = {}
        self._autostart_list_x_range: Tuple[int, int] = (0, 0)

        # Estado del buscador global (spotlight/command palette)
        self.search_open: bool = False
        self.search_query: str = ""
        self.search_results: List[Tuple[int, int, SectionItem]] = []  # (section_idx, item_idx, item)
        self.search_selected_idx: int = 0
        self.search_scroll_offset: int = 0
        self.hover_search_idx: Optional[int] = None
        self._search_click_map: Dict[int, int] = {}  # screen_row → result_idx
        self._search_box_bounds: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (y1, y2, x1, x2)

        # Mapeos de coordenadas para interacción con el ratón y estado hover (pasar el cursor)
        self._sidebar_click_map: Dict[int, int] = {}
        self._content_click_map: Dict[int, Dict[str, Any]] = {}
        self._button_click_map: Dict[str, Tuple[int, int]] = {}
        self._button_row_range: Tuple[int, int] = (0, 0)
        self.selected_button_idx = 2  # 0: Restablecer, 1: Cancelar, 2: Aplicar/Guardar
        self.hover_sidebar_idx: Optional[int] = None
        self.hover_item_idx: Optional[int] = None
        self.hover_subcontrol: Optional[str] = None
        self.hover_button_key: Optional[str] = None
        self.hover_modal_btn_idx: Optional[int] = None

        # Inicializar definiciones de variables por sección
        self.section_items = self._init_section_items()

    def _ensure_background_fixes(self) -> None:
        """Aplica correcciones silenciosas (hook de actualización y logo fastfetch) sin botones en el panel."""
        try:
            self.install_update_hook()
            LizarbeManager.ensure_fastfetch_logo()
        except Exception:
            pass

    def _get_active_sections(self) -> List[Tuple[str, str, str, str, str]]:
        """Devuelve la lista de secciones según la ventana activa ('main' o 'theme_creator')."""
        return self.CREATOR_SECTIONS if self.view_mode == "theme_creator" else self.SECTIONS

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

    def _sync_keybinds_into_settings(self) -> None:
        """Sincroniza el resumen de atajos dentro de self.settings para detección de cambios."""
        for idx, entry in enumerate(self.keybind_items):
            self.settings[f"kb_entry_{idx}"] = f"{entry.get('keys')}|{entry.get('cmd')}|{entry.get('enabled')}"

    def _build_autostart_section_items(self) -> List[SectionItem]:
        """Construye dinámicamente los controles de la sección Autostart."""
        items = [
            SectionItem(
                "action:add_autostart",
                "Agregar entrada",
                "Aplicacion, servicio o comando",
                "action",
            ),
        ]
        for idx, entry in enumerate(self.autostart_items):
            cmd = entry.get("cmd", "")
            kind = entry.get("kind", "launch")
            kind_lbl = "Aplicacion" if kind == "launch" else "Comando"
            items.append(
                SectionItem(
                    f"autostart:item:{idx}",
                    cmd,
                    f"{kind_lbl} │ Supr: Eliminar",
                    "toggle",
                )
            )
        return items

    def _build_keybinds_section_items(self) -> List[SectionItem]:
        """Construye la lista completa de atajos de teclado del sistema para visualizar y editar."""
        items = [
            SectionItem(
                "action:add_keybind",
                "Nuevo atajo",
                "Agregar atajo personalizado",
                "action",
            ),
            SectionItem("binds:hide_special", "Ocultar scratchpad", "Al cambiar de escritorio", "toggle"),
            SectionItem("binds:workspace_back_forth", "Ida y vuelta", "Volver al escritorio previo", "toggle"),
            SectionItem("binds:allow_cycles", "Ciclos de escritorio", "Navegar historial", "toggle"),
        ]
        current_cat = None
        for idx, entry in enumerate(self.keybind_items):
            cat = str(entry.get("category", "SISTEMA"))
            if cat != current_cat:
                current_cat = cat
                items.append(
                    SectionItem(
                        f"header:kb_{cat}",
                        cat,
                        "Clic: Editar │ Clic der: Menu",
                        "header",
                    )
                )
            title = str(entry.get("title", ""))
            cmd_desc = str(entry.get("cmd", ""))
            items.append(
                SectionItem(
                    f"keybind:item:{idx}",
                    title,
                    cmd_desc,
                    "action",
                )
            )
        return items

    def _build_bar_section_items(self) -> List[SectionItem]:
        """Construye los controles de la pestaña Barra Superior de Omarchy."""
        items = [
            SectionItem("bar:visible", "Mostrar barra", "Visible en pantalla", "toggle"),
            SectionItem("bar:position", "Posicion", "Ubicacion en pantalla", "select", options=["top", "bottom", "left", "right"]),
            SectionItem("bar:transparent", "Fondo transparente", "Superficie sin fondo solido", "toggle"),
            SectionItem("bar:center_anchor", "Ancla central", "Widget fijo al centro", "select", options=["omarchy.clock", "omarchy.workspaces", "none"]),
            SectionItem(
                "bar:clock_format",
                "Formato del reloj",
                "Formato de fecha y hora",
                "select",
                options=["ddd d MMM h:mm AP", "ddd d MMM HH:mm", "HH:mm", "h:mm AP", "HH:mm:ss"],
            ),
            SectionItem(
                "bar:clock_alt_format",
                "Formato secundario",
                "Al hacer clic en el reloj",
                "select",
                options=["d MMMM 'W'ww yyyy", "dddd, d MMMM yyyy", "yyyy-MM-dd"],
            ),
            SectionItem("bar:idle_screensaver", "Salvapantallas (s)", "Tiempo de inactividad", "stepper", 0, 1800, 30),
            SectionItem("bar:idle_lock", "Bloqueo (s)", "Tiempo para bloquear sesion", "stepper", 0, 3600, 60),
            SectionItem("action:reset_bar_defaults", "Restaurar barra", "Diseño original", "action"),
            SectionItem("action:restart_shell", "Reiniciar barra", "Recargar shell", "action"),
            SectionItem(
                "header:bar_widgets",
                "WIDGETS",
                "Posicion en la barra",
                "header",
            ),
        ]
        for w_id, s_key, w_label, _ in ConfigSync.BAR_WIDGETS:
            items.append(
                SectionItem(
                    f"bar_widget:{s_key}",
                    w_label,
                    w_id,
                    "select",
                    options=["off", "left", "center", "right"],
                )
            )
        return items

    def _color_options_for(self, current_hex: str) -> List[str]:
        """Construye la lista de opciones de un selector de color con previsualización y entrada #Hex."""
        base = [str(current_hex), "Escribir #Hex..."]
        for c in self.CURATED_HEX_PALETTE:
            if c not in base:
                base.append(c)
        return base

    def _build_creator_section_items(self, sec_id: str) -> List[SectionItem]:
        """Construye los controles de cada categoría en la ventana dedicada de Creación/Edición de Temas Omarchy."""
        spec = self.theme_creator_spec
        themes = self.available_themes if self.available_themes else ["tokyo-night", "lizarbe", "catppuccin", "rose-pine"]

        if sec_id == "creator_identity":
            icon_opts = list(dict.fromkeys([
                str(spec.get("icons", "Yaru-blue")),
                "Yaru-red", "Yaru-blue", "Yaru-purple", "Yaru-sage", "Yaru-olive",
                "Yaru-magenta", "Papirus-Dark", "Papirus-Light", "Adwaita", "Lizarbe-Red",
            ]))
            return [
                SectionItem("creator:name", "Nombre", "Identificador del tema", "action"),
                SectionItem("creator:base_theme", "Plantilla base", "Tema de referencia", "select", options=themes),
                SectionItem("creator:mode", "Modo", "Oscuro o claro", "select", options=["dark", "light"]),
                SectionItem("creator:icons", "Iconos", "Paquete de iconos", "select", options=icon_opts),
            ]

        if sec_id == "creator_borders":
            return [
                SectionItem("creator:accent", "Acento", "Color principal", "select", options=self._color_options_for(spec.get("accent", "#7aa2f7"))),
                SectionItem("creator:active_border", "Borde activo", "Ventana enfocada", "select", options=self._color_options_for(spec.get("active_border", "#7aa2f7"))),
                SectionItem("creator:inactive_border", "Borde inactivo", "Ventana sin foco", "select", options=self._color_options_for(spec.get("inactive_border", "#414868"))),
                SectionItem("creator:selection", "Seleccion", "Resaltado en menus", "select", options=self._color_options_for(spec.get("selection", "#292e42"))),
                SectionItem("creator:muted", "Secundario", "Bordes y texto tenue", "select", options=self._color_options_for(spec.get("muted", "#414868"))),
            ]

        if sec_id == "creator_widgets":
            return [
                SectionItem("creator:widget_bg", "Fondo de widgets", "Barra, lanzador y menus", "select", options=self._color_options_for(spec.get("widget_bg", "#1a1b26"))),
                SectionItem("creator:widget_fg", "Texto de widgets", "Fuente en barra y menus", "select", options=self._color_options_for(spec.get("widget_fg", "#a9b1d6"))),
                SectionItem("creator:widget_border", "Borde de widgets", "Contorno de menus y OSD", "select", options=self._color_options_for(spec.get("widget_border", "#7aa2f7"))),
                SectionItem("creator:widget_alpha", "Opacidad", "Transparencia de widgets", "slider", 0.10, 1.00, 0.05),
            ]

        if sec_id == "creator_media":
            wp_sources = self.theme_engine.list_wallpaper_options()
            cur_wp_src = str(spec.get("wallpapers_source", f"tema:{spec.get('base_theme', 'tokyo-night')}"))
            if cur_wp_src not in wp_sources:
                wp_sources.insert(0, cur_wp_src)
            wp_sources.append("Escribir ruta...")

            custom_wps = self.theme_engine.list_custom_wallpaper_files()
            cur_cwp = str(spec.get("custom_wallpaper", "ninguno"))
            if cur_cwp not in custom_wps:
                custom_wps.insert(0, cur_cwp)
            custom_wps.append("Escribir ruta...")

            prev_opts = ["usar_fondo"] + [f"tema:{t}" for t in themes] + ["Escribir ruta..."]
            cur_prev = str(spec.get("preview_source", f"tema:{spec.get('base_theme', 'tokyo-night')}"))
            if cur_prev not in prev_opts:
                prev_opts.insert(0, cur_prev)

            return [
                SectionItem("creator:wallpapers_source", "Fondos", "Carpeta de fondos", "select", options=wp_sources),
                SectionItem("creator:custom_wallpaper", "Fondo extra", "Imagen adicional", "select", options=custom_wps),
                SectionItem("creator:preview_source", "Preview", "Imagen de vista previa", "select", options=prev_opts),
            ]

        if sec_id == "creator_terminal":
            return [
                SectionItem("creator:background", "Fondo", "Fondo principal", "select", options=self._color_options_for(spec.get("background", "#1a1b26"))),
                SectionItem("creator:dark_background", "Fondo oscuro", "Tono secundario", "select", options=self._color_options_for(spec.get("dark_background", "#13141c"))),
                SectionItem("creator:lighter_background", "Fondo elevado", "Paneles en terminal", "select", options=self._color_options_for(spec.get("lighter_background", "#24283b"))),
                SectionItem("creator:foreground", "Texto", "Texto principal", "select", options=self._color_options_for(spec.get("foreground", "#a9b1d6"))),
                SectionItem("creator:bright_foreground", "Texto brillante", "Texto resaltado", "select", options=self._color_options_for(spec.get("bright_foreground", "#c0caf5"))),
                SectionItem("creator:red", "Rojo", "ANSI red", "select", options=self._color_options_for(spec.get("red", "#f7768e"))),
                SectionItem("creator:green", "Verde", "ANSI green", "select", options=self._color_options_for(spec.get("green", "#9ece6a"))),
                SectionItem("creator:yellow", "Amarillo", "ANSI yellow", "select", options=self._color_options_for(spec.get("yellow", "#e0af68"))),
                SectionItem("creator:blue", "Azul", "ANSI blue", "select", options=self._color_options_for(spec.get("blue", "#7aa2f7"))),
                SectionItem("creator:magenta", "Magenta", "ANSI magenta", "select", options=self._color_options_for(spec.get("magenta", "#ad8ee6"))),
                SectionItem("creator:cyan", "Cian", "ANSI cyan", "select", options=self._color_options_for(spec.get("cyan", "#449dab"))),
                SectionItem("creator:orange", "Naranja", "ANSI orange", "select", options=self._color_options_for(spec.get("orange", "#eb927b"))),
                SectionItem("creator:bright_red", "Rojo brillante", "ANSI bright red", "select", options=self._color_options_for(spec.get("bright_red", "#ff7a93"))),
                SectionItem("creator:bright_green", "Verde brillante", "ANSI bright green", "select", options=self._color_options_for(spec.get("bright_green", "#b9f27c"))),
                SectionItem("creator:bright_yellow", "Amarillo brillante", "ANSI bright yellow", "select", options=self._color_options_for(spec.get("bright_yellow", "#ff9e64"))),
                SectionItem("creator:bright_blue", "Azul brillante", "ANSI bright blue", "select", options=self._color_options_for(spec.get("bright_blue", "#7da6ff"))),
                SectionItem("creator:bright_magenta", "Magenta brillante", "ANSI bright magenta", "select", options=self._color_options_for(spec.get("bright_magenta", "#bb9af7"))),
                SectionItem("creator:bright_cyan", "Cian brillante", "ANSI bright cyan", "select", options=self._color_options_for(spec.get("bright_cyan", "#0db9d7"))),
            ]

        # creator_extras
        nv_opts = list(dict.fromkeys([
            str(spec.get("neovim_scheme", "tokyonight-night")),
            "tokyonight-night", "catppuccin", "kanagawa", "rose-pine", "nord", "habamax", "gruvbox",
        ]))
        kb_hex = "#" + str(spec.get("keyboard_rgb", "7aa2f7")).lstrip("#")[:6]
        return [
            SectionItem("creator:neovim_scheme", "Neovim", "Esquema de color", "select", options=nv_opts),
            SectionItem("creator:keyboard_rgb", "Teclado RGB", "Color de iluminacion", "select", options=self._color_options_for(kb_hex)),
        ]

    def _build_themes_section_items(self) -> List[SectionItem]:
        """Construye dinámicamente los controles de la sección Temas Omarchy y las tarjetas de temas guardados."""
        self.available_themes = self.theme_engine.list_available_themes()
        themes = self.available_themes if self.available_themes else ["tokyo-night", "lizarbe", "catppuccin", "rose-pine"]
        sel_theme = str(self.settings.get("omarchy_theme_name", self.theme_engine.current_theme))

        items = [
            SectionItem(
                "action:create_theme",
                "Crear tema",
                "Nuevo tema personalizado",
                "action",
            ),
            SectionItem(
                "action:edit_theme",
                "Editar tema",
                f"Modificar '{sel_theme}'",
                "action",
            ),
            SectionItem(
                "action:clone_theme",
                "Duplicar tema",
                f"Copia de '{sel_theme}'",
                "action",
            ),
            SectionItem(
                "action:delete_theme",
                "Borrar tema",
                f"Eliminar '{sel_theme}'",
                "action",
            ),
            SectionItem("omarchy:theme", "Tema", "Tema del sistema", "select", options=themes),
            SectionItem(
                "header:saved_themes",
                "TEMAS GUARDADOS",
                "Clic der: Editar o borrar │ Supr: Borrar",
                "header",
            ),
        ]

        user_themes = self.theme_engine.list_user_themes()
        for u_name in user_themes:
            info = self.theme_engine.get_theme_info(u_name)
            t_icons = info.get("icon_theme", "Adwaita")
            items.append(
                SectionItem(
                    f"user_theme:item:{u_name}",
                    u_name,
                    t_icons,
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
        self.cursor_themes = self.config_sync.list_cursor_themes()
        cur_ct = str(self.settings.get("cursor_theme", "default"))
        if cur_ct and cur_ct not in self.cursor_themes:
            self.cursor_themes.insert(0, cur_ct)

        kb_layouts = ["es", "latam", "us", "us,es", "us,latam", "es,us", "latam,us", "br", "fr", "de", "it", "pt", "gb"]
        cur_kbl = str(self.settings.get("kb_layout", "es"))
        if cur_kbl and cur_kbl not in kb_layouts:
            kb_layouts.insert(0, cur_kbl)
        kb_layouts.append("Escribir distribucion...")

        return {
            "general": [
                SectionItem("general:gaps_in", "Gaps internos", "Espacio entre ventanas", "stepper", 0, 30, 1),
                SectionItem("general:gaps_out", "Gaps externos", "Margen de pantalla", "stepper", 0, 50, 1),
                SectionItem("general:border_size", "Grosor de borde", "Tamaño en pixeles", "stepper", 0, 10, 1),
                SectionItem("general:resize_on_border", "Redimensionar en borde", "Arrastrar bordes con el raton", "toggle"),
                SectionItem("general:extend_border_grab_area", "Area de agarre", "Pixeles extra en bordes", "stepper", 0, 30, 1),
                SectionItem("general:hover_icon_on_border", "Icono en borde", "Mostrar cursor al pasar", "toggle"),
                SectionItem("general:layout", "Layout", "Disposicion de ventanas", "select", options=["dwindle", "master", "scrolling"]),
                SectionItem("general:allow_tearing", "Allow tearing", "Menor latencia en juegos", "toggle"),
                SectionItem("general:no_focus_fallback", "Sin salto de foco", "Mantener foco en borde", "toggle"),
                SectionItem("general:snap:enabled", "Ajuste magnetico", "Acoplar ventanas flotantes", "toggle"),
                SectionItem("general:snap:window_gap", "Distancia entre ventanas", "Rango de acoplamiento", "stepper", 0, 40, 2),
                SectionItem("general:snap:monitor_gap", "Distancia al monitor", "Rango a bordes de pantalla", "stepper", 0, 40, 2),
                SectionItem("general:snap:border_overlap", "Superponer bordes", "Unir bordes al acoplar", "toggle"),
            ],
            "decoration": [
                SectionItem("decoration:rounding", "Redondeo", "Esquinas en pixeles", "stepper", 0, 30, 1),
                SectionItem("decoration:rounding_power", "Curvatura", "Suavidad de esquinas", "slider", 1.0, 5.0, 0.25),
                SectionItem("decoration:active_opacity", "Opacidad activa", "Ventana enfocada", "slider", 0.1, 1.0, 0.05),
                SectionItem("decoration:inactive_opacity", "Opacidad inactiva", "Ventanas sin foco", "slider", 0.1, 1.0, 0.05),
                SectionItem("decoration:fullscreen_opacity", "Opacidad fullscreen", "Pantalla completa", "slider", 0.1, 1.0, 0.05),
                SectionItem("decoration:dim_inactive", "Atenuar inactivas", "Oscurecer ventanas sin foco", "toggle"),
                SectionItem("decoration:dim_strength", "Nivel de atenuado", "Intensidad en inactivas", "slider", 0.0, 1.0, 0.05),
                SectionItem("decoration:dim_special", "Atenuar especial", "Fondo de scratchpad", "slider", 0.0, 1.0, 0.05),
                SectionItem("decoration:blur:enabled", "Desenfoque (Blur)", "Fondo translucido", "toggle"),
                SectionItem("decoration:blur:size", "Radio de blur", "Tamaño del desenfoque", "stepper", 1, 20, 1),
                SectionItem("decoration:blur:passes", "Pasadas de blur", "Calidad del filtrado", "stepper", 1, 6, 1),
                SectionItem("decoration:blur:new_optimizations", "Optimizar blur", "Mejor rendimiento", "toggle"),
                SectionItem("decoration:blur:xray", "Blur X-Ray", "Ver fondo a traves de flotantes", "toggle"),
                SectionItem("decoration:blur:ignore_opacity", "Ignorar opacidad", "Blur independiente", "toggle"),
                SectionItem("decoration:blur:vibrancy", "Vibrancia", "Saturacion del blur", "slider", 0.0, 1.0, 0.05),
                SectionItem("decoration:shadow:enabled", "Sombras", "Sombra bajo ventanas", "toggle"),
                SectionItem("decoration:shadow:range", "Tamaño de sombra", "Radio en pixeles", "stepper", 1, 40, 1),
                SectionItem("decoration:shadow:render_power", "Intensidad de sombra", "Degradado (1-4)", "stepper", 1, 4, 1),
                SectionItem("decoration:shadow:sharp", "Sombra nitida", "Sin difuminado", "toggle"),
            ],
            "animations": [
                SectionItem("animations:enabled", "Animaciones", "Transiciones globales", "toggle"),
                SectionItem("animations:workspace_wraparound", "Salto continuo", "Del ultimo al primero", "toggle"),
                SectionItem("animations:preset", "Perfil", "Ritmo de curvas", "select", options=["omarchy", "smooth", "snappy", "minimal"]),
                SectionItem("animations:windows", "Estilo de ventanas", "Al abrir y cerrar", "select", options=["popin 87%", "popin 80%", "slide", "gnomed"]),
                SectionItem("animations:windows_speed", "Velocidad", "Rapidez de ventanas", "slider", 1.0, 10.0, 0.5),
                SectionItem("animations:fade_enabled", "Desvanecimiento", "Efecto fade", "toggle"),
                SectionItem("animations:layers", "Capas y menus", "Animacion de paneles", "select", options=["fade", "slide", "popin 80%"]),
                SectionItem("animations:workspaces_enabled", "Animar escritorios", "Al cambiar de escritorio", "toggle"),
                SectionItem("animations:workspaces", "Estilo de escritorios", "Tipo de transicion", "select", options=["slide", "slidevert", "fade", "slidefade 20%"]),
                SectionItem("animations:special", "Escritorio especial", "Transicion de scratchpad", "select", options=["slidevert", "slide", "fade"]),
            ],
            "cursor": [
                SectionItem("cursor:theme", "Tema del cursor", "Estilo del puntero", "select", options=self.cursor_themes),
                SectionItem("cursor:size", "Tamaño", "Puntero en pixeles", "select", options=["16", "20", "24", "28", "32", "48"]),
                SectionItem("cursor:no_hardware_cursors", "Cursor por software", "Evitar parpadeos", "toggle"),
                SectionItem("cursor:inactive_timeout", "Ocultar inactivo (s)", "0 = nunca", "stepper", 0, 30, 1),
                SectionItem("cursor:hide_on_key_press", "Ocultar al escribir", "Al presionar teclas", "toggle"),
                SectionItem("cursor:hide_on_touch", "Ocultar al tocar", "En pantalla tactil", "toggle"),
                SectionItem("cursor:warp_on_change_workspace", "Centrar al cambiar", "Mover a ventana activa", "stepper", 0, 2, 1),
                SectionItem("cursor:zoom_factor", "Zoom", "Lupa del puntero", "slider", 1.0, 3.0, 0.25),
                SectionItem("cursor:zoom_rigid", "Zoom rigido", "Seguir el puntero", "toggle"),
            ],
            "keybinds": self._build_keybinds_section_items(),
            "devices": [
                SectionItem("header:input_kb", "TECLADO", "Distribucion y repeticion", "header"),
                SectionItem("input:kb_layout", "Distribucion", "Idioma del teclado", "select", options=kb_layouts),
                SectionItem("input:kb_variant", "Variante", "Disposicion de teclas", "select", options=["none", "intl", "deadtilde", "nodeadkeys", "winkeys", "dvorak", "colemak"]),
                SectionItem("input:kb_grp_toggle", "Cambiar idioma", "Atajo entre distribuciones", "select", options=["Ninguno", "Alt + Shift", "Super + Espacio", "Ctrl + Shift", "Alt Izq + Alt Der"]),
                SectionItem("input:compose_key", "Tecla Compose", "Para caracteres especiales", "select", options=[
                    "Desactivada (Recomendado para @)",
                    "Bloq Mayús (Caps Lock)",
                    "Tecla Menú",
                    "Super / Win Derecho",
                    "Impr Pant (PrtSc)",
                    "Insert",
                    "Pausa (Pause)",
                    "Alt Gr (Desactiva @)",
                    "󰌌 Pulsar tecla para asignar...",
                ]),
                SectionItem("action:record_compose", "Asignar Compose con tecla", "Pulsar una tecla fisica", "action"),
                SectionItem("action:fix_caps", "Restaurar Bloq Mayus y @", "Desactiva Compose y bloqueos", "action"),
                SectionItem("input:repeat_rate", "Velocidad de repeticion", "Pulsaciones por segundo", "stepper", 10, 100, 5),
                SectionItem("input:repeat_delay", "Retardo de repeticion", "Espera inicial (ms)", "stepper", 150, 600, 25),
                SectionItem("input:numlock_by_default", "Bloq Num al iniciar", "Activar teclado numerico", "toggle"),
                SectionItem("header:input_mouse", "RATON Y TOUCHPAD", "Puntero, scroll y gestos", "header"),
                SectionItem("input:follow_mouse", "Seguir al raton", "Enfocar al mover (0-3)", "stepper", 0, 3, 1),
                SectionItem("input:mouse_refocus", "Reenfocar con raton", "Al cruzar bordes", "toggle"),
                SectionItem("input:sensitivity", "Sensibilidad", "Velocidad del puntero", "slider", -1.0, 1.0, 0.05),
                SectionItem("input:accel_profile", "Aceleracion", "Curva de movimiento", "select", options=["flat", "adaptive"]),
                SectionItem("input:mouse_natural_scroll", "Scroll natural (Raton)", "Invertir rueda", "toggle"),
                SectionItem("input:left_handed", "Modo zurdo", "Invertir botones", "toggle"),
                SectionItem("input:touchpad:natural_scroll", "Scroll natural (Touchpad)", "Desplazamiento inverso", "toggle"),
                SectionItem("input:touchpad:scroll_factor", "Velocidad de scroll", "En el touchpad", "slider", 0.1, 2.0, 0.1),
                SectionItem("input:touchpad:clickfinger_behavior", "Clic multifinger", "2 dedos = der, 3 = medio", "toggle"),
                SectionItem("input:touchpad:tap-to-click", "Toque para clic", "Clic suave en touchpad", "toggle"),
                SectionItem("input:touchpad:disable_while_typing", "Desactivar al escribir", "Evitar toques accidentales", "toggle"),
                SectionItem("input:touchpad:drag_3fg", "Arrastre con 3 dedos", "0=Off, 1=On, 2=Bloqueo", "stepper", 0, 2, 1),
                SectionItem("gestures:workspace_swipe", "Gesto de escritorios", "Deslizar con 3 dedos", "toggle"),
            ],
            "monitors": [
                SectionItem("display:scale", "Escala", "Tamaño de interfaz", "select", options=self.scales),
                SectionItem("display:mode", "Resolucion y Hz", "Modo de pantalla", "select", options=mon_modes),
                SectionItem("display:transform", "Rotacion", "Orientacion de pantalla", "select", options=["0 (Normal)", "1 (90 grados)", "2 (180 grados)", "3 (270 grados)"]),
                SectionItem("display:gdk_scale", "Escala GTK", "Aplicaciones X11/GTK", "select", options=["1", "2"]),
                SectionItem("display:vrr", "Frecuencia variable", "FreeSync / G-Sync", "select", options=["0 (Desactivado)", "1 (Siempre activo)", "2 (Solo pantalla completa)"]),
                SectionItem("display:xwayland_zero_scaling", "XWayland nitido", "Sin reescalado borroso", "toggle"),
                SectionItem("action:save_monitor", "Guardar monitor", "Escribir monitors.lua", "action"),
            ],
            "workspaces": [
                SectionItem("workspace:count", "Escritorios fijos", "Cantidad persistente", "stepper", 1, 10, 1),
                SectionItem("workspace:layout_toggle", "Layout por defecto", "Disposicion en escritorios", "select", options=["dwindle", "scrolling", "master"]),
                SectionItem("misc:focus_on_activate", "Enfocar al abrir", "Atender nuevas ventanas", "toggle"),
                SectionItem("misc:dpms_key", "Despertar con teclado", "Encender pantalla", "toggle"),
                SectionItem("misc:dpms_mouse", "Despertar con raton", "Encender al mover", "toggle"),
                SectionItem("misc:focus_under_fs", "Foco en fullscreen", "Comportamiento (0-2)", "stepper", 0, 2, 1),
                SectionItem("misc:animate_resizes", "Animar redimension", "Al ajustar tamaño", "toggle"),
                SectionItem("misc:animate_dragging", "Animar arrastre", "Al mover ventanas", "toggle"),
            ],
            "layouts": [
                SectionItem("dwindle:force_split", "Direccion de division", "0=Raton, 1=Izq, 2=Der", "stepper", 0, 2, 1),
                SectionItem("dwindle:preserve_split", "Conservar division", "Mantener orientacion", "toggle"),
                SectionItem("dwindle:smart_split", "Division inteligente", "Segun posicion del cursor", "toggle"),
                SectionItem("dwindle:smart_resizing", "Redimension inteligente", "Segun direccion del raton", "toggle"),
                SectionItem("dwindle:split_ratio", "Proporcion de division", "Tamaño relativo", "slider", 0.5, 1.5, 0.05),
                SectionItem("layout:single_window_aspect", "Proporcion ventana unica", "En pantallas anchas", "select", options=["0 0", "1 1", "4 3", "16 9"]),
                SectionItem("master:new_status", "Nuevas en Master", "Posicion inicial", "select", options=["master", "slave", "inherit"]),
                SectionItem("master:mfact", "Tamaño Master", "Ancho de columna principal", "slider", 0.20, 0.80, 0.05),
                SectionItem("master:orientation", "Orientacion Master", "Ubicacion principal", "select", options=["left", "right", "top", "bottom", "center"]),
                SectionItem("scrolling:column_width", "Ancho en Scrolling", "Tamaño de columna", "slider", 0.25, 1.0, 0.02),
                SectionItem("group:groupbar:enabled", "Barra de grupos", "Pestañas en grupos", "toggle"),
                SectionItem("group:groupbar:font_size", "Fuente de grupo", "Tamaño de texto", "stepper", 8, 20, 1),
                SectionItem("group:groupbar:height", "Altura de barra", "Alto en pixeles", "stepper", 14, 36, 2),
                SectionItem("group:groupbar:gradients", "Degradado en grupos", "Fondo estilizado", "toggle"),
            ],
            "rules": [
                SectionItem("rules:terminal_scroll", "Scroll en terminal", "Velocidad del touchpad", "slider", 0.2, 3.0, 0.1),
                SectionItem("rules:browser_opaque", "Navegadores opacos", "Sin transparencia", "toggle"),
                SectionItem("rules:media_opaque", "Multimedia opaco", "Video sin transparencia", "toggle"),
                SectionItem("rules:pavucontrol_float", "Pavucontrol flotante", "Control de audio centrado", "toggle"),
                SectionItem("rules:calculator_float", "Calculadora flotante", "Ventana centrada", "toggle"),
                SectionItem("rules:pip_float", "Picture-in-Picture", "Flotante y fijo", "toggle"),
                SectionItem("rules:steam_float", "Steam flotante", "Amigos y dialogos", "toggle"),
                SectionItem("rules:localsend_float", "LocalSend flotante", "Ventana centrada", "toggle"),
            ],
            "autostart": self._build_autostart_section_items(),
            "bar": self._build_bar_section_items(),
            "themes": self._build_themes_section_items(),
            "omarchy": [
                SectionItem("omarchy:theme", "Tema", "Tema del sistema", "select", options=themes),
                SectionItem("action:next_wallpaper", "Siguiente fondo", "Cambiar fondo actual", "action"),
                SectionItem("action:toggle_bar", "Alternar barra", "Mostrar u ocultar barra", "action"),
                SectionItem("action:toggle_nightlight", "Luz nocturna", "Filtro calido de pantalla", "action"),
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
        if self._was_tiled is None:
            self._was_tiled = HyprIPC.ensure_floating_centered(width=680, height=960)
        else:
            HyprIPC.ensure_floating_centered(width=680, height=960)

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
                try:
                    self.render()
                    self.handle_input(fd)
                except KeyboardInterrupt:
                    self.running = False
                except Exception as exc:
                    self.modal_state = None
                    self.dropdown_open = False
                    self.context_menu_open = False
                    self.status_message = f"Error: {exc}"
        finally:
            if getattr(self, "modal_kb_recording", False):
                self._stop_keybind_recording()
            # Deshabilitar ratón y hover, reactivar auto-wrap (?7h), restaurar modo de teclado (\033[<1u), mostrar cursor y salir de alternate buffer
            sys.stdout.write("\033[<1u\033[?1006l\033[?1003l\033[?1002l\033[?1000l\033[?7h\033[?25h\033[?1049l\033[0m")
            sys.stdout.flush()
            if self.orig_termios:
                termios.tcsetattr(fd, termios.TCSADRAIN, self.orig_termios)
            if self._was_tiled:
                HyprIPC.restore_tiled()

    # ==========================
    # RENDERIZADO CON POSICIONAMIENTO EXACTO
    # ==========================

    @staticmethod
    def _extract_hex_color(text: str) -> Optional[str]:
        """Extrae un código de color hexadecimal #RRGGBB si está presente en el texto."""
        m = re.search(r"#([0-9a-fA-F]{6})\b", str(text))
        if m:
            return f"#{m.group(1)}"
        return None

    def _get_sidebar_width(self, cols: int) -> int:
        return 22 if cols < 95 else 26

    def render(self) -> None:
        cols, rows = shutil.get_terminal_size((84, 42))
        sidebar_w = self._get_sidebar_width(cols)
        content_w = max(30, cols - sidebar_w - 1)
        buf: List[str] = []

        # 1. Barra de Título Superior en fila exacta 1 (\033[1;1H)
        if self.view_mode == "theme_creator":
            t_name = self.theme_creator_spec.get("name", "nuevo-tema")
            t_base = self.theme_creator_spec.get("base_theme", self.theme_engine.current_theme)
            mode_lbl = "EDITAR TEMA" if self.creator_is_editing else "NUEVO TEMA"
            title_left = f" {mode_lbl}: {t_name} "
            title_right = f"Base: {t_base} │ Esc: Cancelar "
        else:
            ver = HyprIPC.get_version_info()
            title_left = " MECA HyprConfig "
            unsaved_badge = " *PENDIENTE* | " if self.has_unsaved_changes() else ""
            title_right = f"{unsaved_badge}Hyprland {ver} | Tema: {self.theme_engine.current_theme} | q/Esc: Salir "
            if len(title_left) + len(title_right) > cols:
                title_right = f"{unsaved_badge}Tema: {self.theme_engine.current_theme} | q/Esc: Salir "

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
        if self.view_mode == "theme_creator":
            keys_hint = " Esc/c: Cancelar │ b: Panel izq │ a: Guardar "
        else:
            keys_hint = " /: Buscar │ Tab: Foco │ b: Panel izq │ m: Menú │ Espacio: Conmutar │ a: Aplicar │ q: Salir "
            if cols < 125:
                keys_hint = " /: Buscar │ Tab: Foco │ b: Panel izq │ m: Menú │ a: Aplicar │ q: Salir "
            if cols < 95:
                keys_hint = " /:Buscar │ b: Panel izq │ m: Menú │ a: Aplicar │ q: Salir "
            if cols < 75:
                keys_hint = " /:Buscar │ b:Izq │ a:Aplicar │ q:Salir "
        max_status_w = max(8, cols - len(keys_hint) - 1)
        status_txt = f" {self.status_message}"[:max_status_w]
        footer_space = max(0, cols - 1 - len(status_txt) - len(keys_hint))
        footer_line = (status_txt + (" " * footer_space) + keys_hint)[:cols - 1]
        buf.append(f"\033[{rows};1H" + self.theme_engine.style("bright_foreground", "muted", footer_line) + "\033[K")

        # 4. Menú desplegable (Dropdown) si está abierto sobre una opción "select"
        if self.dropdown_open and not self.modal_state:
            buf.extend(self._render_dropdown_overlay(cols, rows, sidebar_w))

        # 5. Menú contextual de clic secundario (Right-Click Context Menu)
        if self.context_menu_open and not self.modal_state:
            buf.extend(self._render_context_menu_overlay(cols, rows))

        # 5.5 Buscador Global
        if getattr(self, "search_open", False) and not self.modal_state:
            buf.extend(self._render_search_overlay(cols, rows))

        # 6. Ventana Modal (si está activa)
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
        active_sections = self._get_active_sections()

        for idx, (cat, sec_id, icon, title, desc) in enumerate(active_sections):
            if cat != current_cat:
                if current_cat is not None and len(lines) < max_rows:
                    lines.append(" " * width)

                current_cat = cat
                if len(lines) < max_rows:
                    lines.append(self.theme_engine.style("muted", None, f" {cat}".ljust(width)[:width], bold=True))

            if len(lines) >= max_rows:
                break

            is_sel = (idx == self.current_section_idx)
            is_hover = (idx == self.hover_sidebar_idx and not self.modal_state and not self.dropdown_open and not self.context_menu_open)
            is_active_pane = (self.active_pane == "sidebar" and not self.modal_state and not self.dropdown_open and not self.context_menu_open)

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
        Renderiza un tema guardado con contenedor de tarjeta cuadrada:
        - Cuando está seleccionado (is_chosen), resalta su borde haciéndolo más grueso (┏━━━┓ / ┃...┃ / ┗━━━┛).
        - Muestra el nombre del tema, solo el icono del modo (󰖔 oscuro / 󰖨 claro) y el tema de iconos,
          sin indicadores de texto "seleccionado".
        """
        u_name = item.name
        info = self.theme_engine.get_theme_info(u_name)
        mode = info.get("mode", "dark")
        icons = info.get("icon_theme", "Adwaita")

        u_slug = self.theme_engine.normalize_theme_slug(u_name)
        sel_slug = self.theme_engine.normalize_theme_slug(
            str(self.settings.get("omarchy_theme_name", self.theme_engine.current_theme))
        )

        is_chosen = (u_slug == sel_slug)

        card_w = max(28, width - 3)
        inner_w = card_w - 2

        border_col = "accent" if is_chosen else ("bright_foreground" if (is_sel or is_hover) else "muted")
        card_bg = (
            "soft_hover"
            if is_hover
            else ("soft_selection" if (is_chosen or is_sel) else None)
        )

        mode_icon = "󰖔" if mode == "dark" else "󰖨"
        left_str = f"  {u_name}"
        right_str = f"  {mode_icon}  {icons}  "
        avail_left_w = max(6, inner_w - len(right_str))
        left_padded = left_str[:avail_left_w].ljust(avail_left_w)
        inner_plain = (left_padded + right_str)[:inner_w].ljust(inner_w)

        is_bold_card = (is_chosen or is_sel or is_hover)
        if is_chosen:
            # Borde grueso para la tarjeta seleccionada
            top_border = " " + self.theme_engine.style(border_col, None, "┏" + ("━" * inner_w) + "┓", bold=True)
            bot_border = " " + self.theme_engine.style(border_col, None, "┗" + ("━" * inner_w) + "┛", bold=True)
            side_char = "┃"
        else:
            # Borde delgado estándar
            top_border = " " + self.theme_engine.style(border_col, None, "┌" + ("─" * inner_w) + "┐", bold=is_bold_card)
            bot_border = " " + self.theme_engine.style(border_col, None, "└" + ("─" * inner_w) + "┘", bold=is_bold_card)
            side_char = "│"

        inner_styled = self.theme_engine.style("bright_foreground" if is_bold_card else "foreground", card_bg, inner_plain, bold=is_bold_card)

        mid_line = (
            " "
            + self.theme_engine.style(border_col, None, side_char, bold=is_bold_card)
            + inner_styled
            + self.theme_engine.style(border_col, None, side_char, bold=is_bold_card)
        )

        return top_border, mid_line, bot_border, (1, card_w)

    def _render_content(self, width: int, max_rows: int, sidebar_w: int) -> List[str]:
        lines: List[str] = []
        active_sections = self._get_active_sections()
        if self.current_section_idx >= len(active_sections):
            self.current_section_idx = 0
        sec_meta = active_sections[self.current_section_idx]
        sec_id = sec_meta[1]
        sec_title = sec_meta[3]
        sec_desc = sec_meta[4]
        self._content_click_map.clear()

        # Encabezado de la Sección Activa (3 líneas: screen_y 2, 3, 4)
        lines.append(" " + self.theme_engine.style("bright_foreground", None, sec_title.upper(), bold=True))
        lines.append(" " + self.theme_engine.fg("muted", sec_desc[:width - 2]))
        lines.append(" " + self.theme_engine.fg("muted", "─" * max(1, width - 2)))

        if sec_id.startswith("creator_"):
            items = self._build_creator_section_items(sec_id)
            self.section_items[sec_id] = items
        else:
            if sec_id == "autostart":
                self.section_items["autostart"] = self._build_autostart_section_items()
            elif sec_id == "bar":
                self.section_items["bar"] = self._build_bar_section_items()
            elif sec_id == "themes":
                self.section_items["themes"] = self._build_themes_section_items()
            elif sec_id == "keybinds":
                self.section_items["keybinds"] = self._build_keybinds_section_items()
            items = self.section_items.get(sec_id, [])

        is_active_pane = (self.active_pane == "content" and not self.modal_state and not self.context_menu_open)
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

            is_hover_row = (i == self.hover_item_idx and not self.modal_state and not self.dropdown_open and not self.context_menu_open)
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

            is_dimmed_kb = False
            if item.key.startswith("keybind:item:"):
                kb_idx = int(item.key.split(":")[-1])
                if 0 <= kb_idx < len(self.keybind_items):
                    is_dimmed_kb = not bool(self.keybind_items[kb_idx].get("enabled", True))

            if is_sel:
                l1_raw = f" ▌ {item.name}"[:left_max_w].ljust(left_max_w)
                l2_raw = f" ▌ └─ {item.desc}"[:left_max_w].ljust(left_max_w)
                l1_styled = self.theme_engine.style(
                    "muted" if is_dimmed_kb else "bright_foreground",
                    "soft_selection",
                    l1_raw,
                    bold=not is_dimmed_kb,
                )
                l2_styled = self.theme_engine.fg("muted" if is_dimmed_kb else "foreground", l2_raw)
            else:
                l1_raw = f"   {item.name}"[:left_max_w].ljust(left_max_w)
                l2_raw = f"   {item.desc}"[:left_max_w].ljust(left_max_w)
                l1_styled = self.theme_engine.style(
                    "muted" if is_dimmed_kb else "bright_foreground",
                    None,
                    l1_raw,
                    bold=not is_dimmed_kb,
                )
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

        # Renderizar los botones compactos y elegantes (3 líneas de alto)
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
        """Renderiza el menú desplegable interactivo con previsualización de color en códigos Hex."""
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

        max_opt_len = max(
            len(str(o)) + (3 if self._extract_hex_color(str(o)) else 0)
            for o in opts
        )
        inner_w = max(22, min(44, max_opt_len + 8))
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
            is_bold = (is_sel or is_hov or is_cur)

            check = "✓" if is_cur else ("▸" if (is_sel or is_hov) else " ")
            row_bg = "soft_hover" if is_hov else ("soft_selection" if is_sel else "background")
            row_fg = "bright_foreground" if is_bold else "foreground"

            hex_c = self._extract_hex_color(opt_str)
            if hex_c:
                prefix_plain = f" {check} "
                rem_w = max(1, inner_w - len(prefix_plain) - 2)
                suffix_padded = f" {opt_str}"[:rem_w].ljust(rem_w)
                r_c, g_c, b_c = self.theme_engine.hex_to_rgb(hex_c)
                br, bg_v, bb = self.theme_engine.hex_to_rgb(self.theme_engine.colors.get(row_bg, "#1a1b26"))
                swatch_seq = f"\033[48;2;{br};{bg_v};{bb}m\033[38;2;{r_c};{g_c};{b_c}m██\033[0m"
                row_styled = (
                    self.theme_engine.style(row_fg, row_bg, prefix_plain, bold=is_bold)
                    + swatch_seq
                    + self.theme_engine.style(row_fg, row_bg, suffix_padded, bold=is_bold)
                )
            else:
                row_txt = f" {check} {opt_str}"[:inner_w].ljust(inner_w)
                row_styled = self.theme_engine.style(row_fg, row_bg, row_txt, bold=is_bold)

            overlay.append(
                f"\033[{scr_y};{start_x}H"
                + self.theme_engine.style("accent", "background", "┃", bold=True)
                + row_styled
                + self.theme_engine.style("accent", "background", "│", bold=True)
            )

        ftr_hint = " ▼ " if (self.dropdown_scroll + max_vis < len(opts)) else "━━━"
        bot_line = "┗" + ("━" * (inner_w - 3)) + ftr_hint + "┙"
        overlay.append(f"\033[{start_y + max_vis + 1};{start_x}H" + self.theme_engine.style("accent", "background", bot_line, bold=True))
        return overlay

    def _render_3d_buttons(self, width: int, btn_top_screen_y: int, content_start_x: int) -> List[str]:
        """
        Dibuja los botones inferiores compactos de 3 líneas con bisel 3D Unicode:
        - En la ventana principal: Restablecer, Cancelar, Aplicar.
        - En la ventana de creación de tema: Cancelar, Guardar (sin Restablecer).
        """
        self._button_click_map.clear()
        self._button_row_range = (btn_top_screen_y, btn_top_screen_y + 2)

        if self.view_mode == "theme_creator":
            buttons_spec = [
                ("cancel", 1, " Cancelar "),
                ("save", 2, " Guardar "),
            ]
        else:
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
        is_btn_pane = (self.active_pane == "buttons" and not self.modal_state and not self.dropdown_open and not self.context_menu_open)

        for btn_key, btn_idx, label in buttons_spec:
            inner_w = len(label)
            btn_w = inner_w + 2
            is_hover_btn = (self.hover_button_key == btn_key and not self.modal_state and not self.dropdown_open and not self.context_menu_open)
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
        de 3 líneas (┌───┐ / ┃ - │ / ┗━━━┙) con destello suave y previsualización de color en códigos Hex.
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
            val_str = str(val)
            hex_c = self._extract_hex_color(val_str)
            c_hov = (hover_sub == "control") or (self.dropdown_open and self.dropdown_item == item)
            inner_bg = "soft_hover" if c_hov else ("soft_selection" if is_sel else None)
            if hex_c:
                vis_lbl = f" ██ {val_str} ▾ "
                inner_w = len(vis_lbl)
                r_c, g_c, b_c = self.theme_engine.hex_to_rgb(hex_c)
                bg_seq = ""
                if inner_bg:
                    br, bg_v, bb = self.theme_engine.hex_to_rgb(self.theme_engine.colors.get(inner_bg, "#1a1b26"))
                    bg_seq = f"\033[48;2;{br};{bg_v};{bb}m"
                swatch_seq = f"{bg_seq}\033[38;2;{r_c};{g_c};{b_c}m██\033[0m"
                inner_s = (
                    self.theme_engine.style("bright_foreground", inner_bg, " ", bold=(is_sel or c_hov))
                    + swatch_seq
                    + self.theme_engine.style("bright_foreground", inner_bg, f" {val_str} ▾ ", bold=(is_sel or c_hov))
                )
            else:
                raw_lbl = f" {val_str} ▾ "
                inner_w = len(raw_lbl)
                inner_s = self.theme_engine.style("bright_foreground", inner_bg, raw_lbl, bold=(is_sel or c_hov))

            c_top = self.theme_engine.style("accent" if c_hov else b_col, None, "┌" + ("─" * inner_w) + "┐", bold=c_hov)
            c_mid = self.theme_engine.fg("accent" if c_hov else sh_col, "┃") + inner_s + self.theme_engine.fg(b_col, "│")
            c_bot = self.theme_engine.fg("accent" if c_hov else sh_col, "┗" + ("━" * inner_w) + "┙")
            return c_top, c_mid, c_bot, inner_w + 2

        elif item.item_type == "action":
            is_enabled_kb = True
            if item.key == "action:create_theme":
                raw_lbl = " Nuevo "
            elif item.key == "action:edit_theme":
                raw_lbl = " Editar "
            elif item.key == "action:clone_theme":
                raw_lbl = " Duplicar "
            elif item.key == "action:delete_theme":
                raw_lbl = " Borrar "
            elif item.key in ("action:add_keybind", "action:add_autostart"):
                raw_lbl = " + Agregar "
            elif item.key == "creator:name":
                raw_lbl = f" {self.theme_creator_spec.get('name', 'nuevo-tema')} "
            elif item.key.startswith("keybind:item:"):
                kb_idx = int(item.key.split(":")[-1])
                if 0 <= kb_idx < len(self.keybind_items):
                    entry = self.keybind_items[kb_idx]
                    raw_lbl = f" {entry.get('keys', '')} "
                    is_enabled_kb = bool(entry.get("enabled", True))
                else:
                    raw_lbl = " - "
            elif item.key.startswith("user_theme:item:"):
                raw_lbl = " Seleccionar "
            else:
                raw_lbl = " Ejecutar "
            inner_w = len(raw_lbl)
            c_hov = (hover_sub == "control")
            if not is_enabled_kb:
                c_top = self.theme_engine.style("muted", None, "┌" + ("─" * inner_w) + "┐")
                inner_s = self.theme_engine.style("muted", None, raw_lbl)
                c_mid = self.theme_engine.fg("muted", "│") + inner_s + self.theme_engine.fg("muted", "│")
                c_bot = self.theme_engine.fg("muted", "└" + ("─" * inner_w) + "┘")
                return c_top, c_mid, c_bot, inner_w + 2

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

    def _open_context_menu(self, x: int, y: int, sidebar_w: int) -> None:
        """Abre el menú contextual de clic secundario según el elemento bajo el cursor."""
        self.dropdown_open = False
        self.context_menu_x = x
        self.context_menu_y = y
        self.context_menu_idx = 0
        self.hover_context_idx = None
        self.context_menu_target_key = ""

        active_sections = self._get_active_sections()
        sec_id = active_sections[self.current_section_idx][1]

        if x > sidebar_w + 1 and y in self._content_click_map:
            info = self._content_click_map[y]
            self.active_pane = "content"
            self.selected_item_idx = info["item_idx"]
            item: SectionItem = info["item"]
            self.context_menu_target_key = item.key

            if item.item_type == "theme_card" or item.key.startswith("user_theme:item:"):
                t_name = item.name if item.item_type == "theme_card" else item.key.split(":", 2)[-1]
                u_slugs = {self.theme_engine.normalize_theme_slug(u) for u in self.theme_engine.list_user_themes()}
                is_user = self.theme_engine.normalize_theme_slug(t_name) in u_slugs
                menu_items = [
                    (f"theme:select:{t_name}", f"󰸌  Seleccionar '{t_name}'"),
                    (f"theme:edit:{t_name}", f"󰏫  Editar '{t_name}'"),
                    (f"theme:clone:{t_name}", f"󰆏  Duplicar '{t_name}'"),
                    ("theme:new", "󰐕  Nuevo tema"),
                ]
                if is_user:
                    menu_items.append((f"theme:delete:{t_name}", f"󰆴  Borrar '{t_name}'"))
                self.context_menu_items = menu_items
                self.context_menu_open = True
                return

            if item.key.startswith("keybind:item:"):
                kb_idx = int(item.key.split(":")[-1])
                if 0 <= kb_idx < len(self.keybind_items):
                    entry = self.keybind_items[kb_idx]
                    is_en = bool(entry.get("enabled", True))
                    menu_items = [
                        (f"kb:edit_keys:{kb_idx}", "󰌌  Cambiar teclas"),
                        (f"kb:edit_action:{kb_idx}", "󰏫  Editar accion"),
                        (f"kb:toggle:{kb_idx}", "󰔡  Desactivar atajo" if is_en else "󰔡  Activar atajo"),
                    ]
                    if entry.get("is_custom"):
                        menu_items.append((f"kb:delete:{kb_idx}", "󰆴  Eliminar atajo"))
                    else:
                        menu_items.append((f"kb:reset:{kb_idx}", "󰑐  Restaurar original"))
                    menu_items.append(("kb:new", "󰐕  Nuevo atajo"))
                    self.context_menu_items = menu_items
                    self.context_menu_open = True
                    return

            if item.key.startswith("autostart:item:"):
                as_idx = int(item.key.split(":")[-1])
                if 0 <= as_idx < len(self.autostart_items):
                    is_en = bool(self.autostart_items[as_idx].get("enabled", True))
                    self.context_menu_items = [
                        (f"as:toggle:{as_idx}", "󰔡  Desactivar" if is_en else "󰔡  Activar"),
                        (f"as:delete:{as_idx}", "󰆴  Eliminar"),
                        ("as:add", "󰐕  Agregar a Autostart"),
                    ]
                    self.context_menu_open = True
                    return

            if sec_id == "themes":
                cur_t = str(self.settings.get("omarchy_theme_name", self.theme_engine.current_theme))
                u_slugs = {self.theme_engine.normalize_theme_slug(u) for u in self.theme_engine.list_user_themes()}
                is_user = self.theme_engine.normalize_theme_slug(cur_t) in u_slugs
                menu_items = [
                    ("theme:new", "󰐕  Nuevo tema"),
                    (f"theme:edit:{cur_t}", f"󰏫  Editar '{cur_t}'"),
                    (f"theme:clone:{cur_t}", f"󰆏  Duplicar '{cur_t}'"),
                ]
                if is_user:
                    menu_items.append((f"theme:delete:{cur_t}", f"󰆴  Borrar '{cur_t}'"))
                self.context_menu_items = menu_items
                self.context_menu_open = True
                return

            self.context_menu_items = [
                ("item:activate", f"󰏫  Modificar '{item.name[:20]}'"),
                ("item:reset_one", "󰑐  Restablecer opcion"),
                ("app:save", "󰄬  Aplicar cambios"),
                ("app:reset_all", "󰑐  Restablecer todo"),
            ]
            self.context_menu_open = True
            return

        if x <= sidebar_w and y in self._sidebar_click_map:
            s_idx = self._sidebar_click_map[y]
            s_title = active_sections[s_idx][3]
            self.context_menu_items = [
                (f"sec:goto:{s_idx}", f"󰁔  Ir a {s_title}"),
                ("app:save", "󰄬  Aplicar cambios"),
                ("app:reset_all", "󰑐  Restablecer valores"),
                ("app:cancel", "󰅖  Cancelar y salir"),
            ]
            self.context_menu_open = True
            return

        self.context_menu_items = [
            ("app:save", "󰄬  Aplicar cambios"),
            ("app:reset_all", "󰑐  Restablecer valores"),
            ("app:cancel", "󰅖  Cancelar y salir"),
        ]
        self.context_menu_open = True

    def _open_context_menu_for_current_selection(self) -> None:
        """Abre el menú contextual centrado en la opción o categoría seleccionada actualmente por teclado."""
        if self.modal_state or self.dropdown_open:
            return
        cols, rows = shutil.get_terminal_size((84, 42))
        sidebar_w = self._get_sidebar_width(cols)
        self.dropdown_open = False
        self.context_menu_idx = 0
        self.hover_context_idx = None
        self.context_menu_target_key = ""

        if self.active_pane == "sidebar":
            self.context_menu_x = min(cols - 28, 4)
            self.context_menu_y = min(rows - 10, max(3, self.current_section_idx * 2 + 2))
            active_sections = self._get_active_sections()
            if 0 <= self.current_section_idx < len(active_sections):
                s_title = active_sections[self.current_section_idx][3]
                self.context_menu_items = [
                    (f"sec:goto:{self.current_section_idx}", f"󰁔  Ir a {s_title}"),
                    ("app:save", "󰄬  Aplicar cambios"),
                    ("app:reset_all", "󰑐  Restablecer valores"),
                    ("app:cancel", "󰅖  Cancelar y salir"),
                ]
                self.context_menu_open = True
            return

        active_sections = self._get_active_sections()
        sec_id = active_sections[self.current_section_idx][1]
        items = self.section_items.get(sec_id, [])
        if not items or self.selected_item_idx >= len(items):
            return
        item = items[self.selected_item_idx]
        self.context_menu_target_key = item.key
        self.context_menu_x = min(cols - 35, sidebar_w + 4)
        rel_idx = max(0, self.selected_item_idx - self.content_scroll_offset)
        self.context_menu_y = min(rows - 10, max(4, 5 + rel_idx * 3))

        if item.item_type == "theme_card" or item.key.startswith("user_theme:item:"):
            t_name = item.name if item.item_type == "theme_card" else item.key.split(":", 2)[-1]
            u_slugs = {self.theme_engine.normalize_theme_slug(u) for u in self.theme_engine.list_user_themes()}
            is_user = self.theme_engine.normalize_theme_slug(t_name) in u_slugs
            menu_items = [
                (f"theme:select:{t_name}", f"󰸌  Seleccionar '{t_name}'"),
                (f"theme:edit:{t_name}", f"󰏫  Editar '{t_name}'"),
                (f"theme:clone:{t_name}", f"󰆏  Duplicar '{t_name}'"),
                ("theme:new", "󰐕  Nuevo tema"),
            ]
            if is_user:
                menu_items.append((f"theme:delete:{t_name}", f"󰆴  Borrar '{t_name}'"))
            self.context_menu_items = menu_items
            self.context_menu_open = True
            return

        if item.key.startswith("keybind:item:"):
            kb_idx = int(item.key.split(":")[-1])
            if 0 <= kb_idx < len(self.keybind_items):
                entry = self.keybind_items[kb_idx]
                is_en = bool(entry.get("enabled", True))
                menu_items = [
                    (f"kb:edit_keys:{kb_idx}", "󰌌  Cambiar teclas"),
                    (f"kb:edit_action:{kb_idx}", "󰏫  Editar accion"),
                    (f"kb:toggle:{kb_idx}", "󰔡  Desactivar atajo" if is_en else "󰔡  Activar atajo"),
                ]
                if entry.get("is_custom"):
                    menu_items.append((f"kb:delete:{kb_idx}", "󰆴  Eliminar atajo"))
                else:
                    menu_items.append((f"kb:reset:{kb_idx}", "󰑐  Restaurar original"))
                menu_items.append(("kb:new", "󰐕  Nuevo atajo"))
                self.context_menu_items = menu_items
                self.context_menu_open = True
                return

        if item.key.startswith("autostart:item:"):
            as_idx = int(item.key.split(":")[-1])
            if 0 <= as_idx < len(self.autostart_items):
                is_en = bool(self.autostart_items[as_idx].get("enabled", True))
                self.context_menu_items = [
                    (f"as:toggle:{as_idx}", "󰔡  Desactivar" if is_en else "󰔡  Activar"),
                    (f"as:delete:{as_idx}", "󰆴  Eliminar"),
                    ("as:add", "󰐕  Agregar a Autostart"),
                ]
                self.context_menu_open = True
                return

        if sec_id == "themes":
            cur_t = str(self.settings.get("omarchy_theme_name", self.theme_engine.current_theme))
            u_slugs = {self.theme_engine.normalize_theme_slug(u) for u in self.theme_engine.list_user_themes()}
            is_user = self.theme_engine.normalize_theme_slug(cur_t) in u_slugs
            menu_items = [
                ("theme:new", "󰐕  Nuevo tema"),
                (f"theme:edit:{cur_t}", f"󰏫  Editar '{cur_t}'"),
                (f"theme:clone:{cur_t}", f"󰆏  Duplicar '{cur_t}'"),
            ]
            if is_user:
                menu_items.append((f"theme:delete:{cur_t}", f"󰆴  Borrar '{cur_t}'"))
            self.context_menu_items = menu_items
            self.context_menu_open = True
            return

        self.context_menu_items = [
            ("item:activate", f"󰏫  Modificar '{item.name[:20]}'"),
            ("item:reset_one", "󰑐  Restablecer opcion"),
            ("pane:sidebar", "󰁍  Volver a barra lateral (b)"),
            ("app:save", "󰄬  Aplicar cambios"),
            ("app:reset_all", "󰑐  Restablecer todo"),
        ]
        self.context_menu_open = True

    def _render_context_menu_overlay(self, cols: int, rows: int) -> List[str]:
        """Renderiza el menú contextual flotante de clic secundario."""
        self._context_row_map.clear()
        if not self.context_menu_items:
            return []

        max_lbl = max(len(lbl) for _, lbl in self.context_menu_items)
        inner_w = max(24, min(42, max_lbl + 4))
        box_w = inner_w + 2
        box_h = len(self.context_menu_items) + 2

        start_x = min(max(2, self.context_menu_x), max(2, cols - box_w - 1))
        start_y = min(max(2, self.context_menu_y), max(2, rows - box_h - 1))
        self._context_box_bounds = (start_y, start_y + box_h - 1, start_x, start_x + box_w - 1)

        overlay: List[str] = []
        top_line = "┌" + ("─" * inner_w) + "┐"
        overlay.append(f"\033[{start_y};{start_x}H" + self.theme_engine.style("accent", "background", top_line, bold=True))

        for idx, (_, label) in enumerate(self.context_menu_items):
            scr_y = start_y + 1 + idx
            self._context_row_map[scr_y] = idx
            is_sel = (idx == self.context_menu_idx)
            is_hov = (idx == self.hover_context_idx)
            is_hi = (is_sel or is_hov)

            prefix = " ▸ " if is_hi else "   "
            row_txt = f"{prefix}{label}"[:inner_w].ljust(inner_w)
            row_bg = "soft_hover" if is_hov else ("soft_selection" if is_sel else "background")
            row_fg = "bright_foreground" if is_hi else "foreground"

            overlay.append(
                f"\033[{scr_y};{start_x}H"
                + self.theme_engine.style("accent", "background", "┃", bold=True)
                + self.theme_engine.style(row_fg, row_bg, row_txt, bold=is_hi)
                + self.theme_engine.style("accent", "background", "│", bold=True)
            )

        bot_line = "┗" + ("━" * inner_w) + "┙"
        overlay.append(f"\033[{start_y + box_h - 1};{start_x}H" + self.theme_engine.style("accent", "background", bot_line, bold=True))
        return overlay

    def _execute_context_action(self, act_id: str) -> None:
        """Ejecuta una opción seleccionada en el menú contextual de clic secundario."""
        self.context_menu_open = False
        self.hover_context_idx = None

        if act_id.startswith("sec:goto:"):
            s_idx = int(act_id.split(":")[-1])
            self._request_section_change(s_idx, focus_content=True)
            return

        if act_id == "app:save":
            self.save_all()
            return
        if act_id == "app:reset_all":
            self.reset_to_defaults()
            return
        if act_id == "app:cancel":
            self.cancel_changes()
            return
        if act_id == "pane:sidebar":
            self.active_pane = "sidebar"
            self.status_message = "Foco en el panel izquierdo (Barra lateral)."
            return

        if act_id == "item:activate":
            self._activate_current_item()
            return
        if act_id == "item:reset_one":
            key = self.context_menu_target_key
            if key in self.KEY_TO_SETTING:
                s_key, _, def_val = self.KEY_TO_SETTING[key]
                self.settings[s_key] = def_val
                self.status_message = f"Restablecido: {s_key} = {def_val}"
            return

        if act_id == "theme:new":
            self._execute_action("action:create_theme")
            return
        if act_id.startswith("theme:select:"):
            t_name = act_id.split(":", 2)[-1]
            self._set_item_value("omarchy:theme", t_name)
            return
        if act_id.startswith("theme:edit:"):
            t_name = act_id.split(":", 2)[-1]
            self._open_theme_editor(t_name)
            return
        if act_id.startswith("theme:clone:"):
            t_name = act_id.split(":", 2)[-1]
            self.settings["omarchy_theme_name"] = t_name
            self._execute_action("action:clone_theme")
            return
        if act_id.startswith("theme:delete:"):
            t_name = act_id.split(":", 2)[-1]
            self._prompt_delete_theme(t_name)
            return

        if act_id == "kb:new":
            self._execute_action("action:add_keybind")
            return
        if act_id.startswith("kb:edit_keys:"):
            kb_idx = int(act_id.split(":")[-1])
            self._open_keybind_modal(kb_idx, initial_field=0)
            return
        if act_id.startswith("kb:edit_action:"):
            kb_idx = int(act_id.split(":")[-1])
            self._open_keybind_modal(kb_idx, initial_field=1)
            return
        if act_id.startswith("kb:toggle:"):
            kb_idx = int(act_id.split(":")[-1])
            if 0 <= kb_idx < len(self.keybind_items):
                cur_en = bool(self.keybind_items[kb_idx].get("enabled", True))
                self.keybind_items[kb_idx]["enabled"] = not cur_en
                self._sync_keybinds_into_settings()
                self.section_items["keybinds"] = self._build_keybinds_section_items()
                state_str = "activado" if not cur_en else "desactivado"
                self.status_message = f"Atajo '{self.keybind_items[kb_idx].get('title')}' {state_str}."
            return
        if act_id.startswith("kb:reset:"):
            kb_idx = int(act_id.split(":")[-1])
            if 0 <= kb_idx < len(self.keybind_items):
                entry = self.keybind_items[kb_idx]
                entry["keys"] = entry.get("default_keys", entry.get("keys", ""))
                entry["cmd"] = entry.get("default_cmd", entry.get("cmd", ""))
                entry["enabled"] = True
                self._sync_keybinds_into_settings()
                self.section_items["keybinds"] = self._build_keybinds_section_items()
                self.status_message = f"Atajo '{entry.get('title')}' restaurado."
            return
        if act_id.startswith("kb:delete:"):
            kb_idx = int(act_id.split(":")[-1])
            if 0 <= kb_idx < len(self.keybind_items):
                removed = self.keybind_items.pop(kb_idx)
                self._sync_keybinds_into_settings()
                self.section_items["keybinds"] = self._build_keybinds_section_items()
                self.status_message = f"Atajo '{removed.get('title')}' eliminado."
            return

        if act_id == "as:add":
            self._execute_action("action:add_autostart")
            return
        if act_id.startswith("as:toggle:"):
            as_idx = int(act_id.split(":")[-1])
            if 0 <= as_idx < len(self.autostart_items):
                self.autostart_items[as_idx]["enabled"] = not bool(self.autostart_items[as_idx].get("enabled", True))
                self._sync_autostart_into_settings()
                self.section_items["autostart"] = self._build_autostart_section_items()
            return
        if act_id.startswith("as:delete:"):
            as_idx = int(act_id.split(":")[-1])
            if 0 <= as_idx < len(self.autostart_items):
                removed = self.autostart_items.pop(as_idx)
                self._sync_autostart_into_settings()
                self.section_items["autostart"] = self._build_autostart_section_items()
                self.status_message = f"Eliminado de Autostart: {removed.get('cmd')}"
            return

    def _get_filtered_autostart_apps(self) -> List[Dict[str, str]]:
        """Filtra la lista de aplicaciones instaladas según el texto buscado en el modal de Autostart."""
        q = self.modal_input_text.strip().lower()
        if not q:
            return self.installed_apps
        return [
            app for app in self.installed_apps
            if q in app["name"].lower() or q in app["cmd"].lower()
        ]

    def _get_filtered_kb_apps(self) -> List[Dict[str, str]]:
        """Filtra la lista de aplicaciones instaladas según el texto buscado en el selector de programas para el atajo."""
        if not self.installed_apps:
            self.installed_apps = self.config_sync.list_installed_applications()
        q = self.modal_kb_app_search.strip().lower()
        if not q:
            return self.installed_apps
        return [
            app for app in self.installed_apps
            if q in app["name"].lower() or q in app["cmd"].lower()
        ]

    def _select_kb_dropdown_app(self, idx: int) -> None:
        """Selecciona una aplicación de la lista desplegable de programas para el nuevo atajo."""
        filtered = self._get_filtered_kb_apps()
        if 0 <= idx < len(filtered):
            app = filtered[idx]
            self.modal_kb_app_selected_cmd = app["cmd"].strip()
            self.modal_kb_app_selected_name = app["name"].strip()
            if not self.modal_kb_desc.strip() or self.modal_kb_desc.strip() == "Nuevo atajo":
                self.modal_kb_desc = app["name"].strip()
            self.modal_kb_app_dropdown_open = False
            self.modal_kb_app_search = ""
            self.modal_kb_field = 2  # Salta a casilla de comandos extras
            self.status_message = f"✓ Programa seleccionado: {app['name']}"

    def _get_keybind_max_field(self) -> int:
        """Retorna el índice del último campo de entrada antes de la botonera en el modal de atajo."""
        if self.modal_state == "add_keybind":
            return 3 if getattr(self, "modal_kb_tab", "program") == "program" else 2
        return 1

    def _render_modal_overlay(self, cols: int, rows: int) -> List[str]:
        """Renderiza ventanas modales centradas."""
        self._modal_button_click_map.clear()
        self._modal_kind_click_range = (0, 0, 0)
        self._modal_mode_click_range = (0, 0, 0)
        self._autostart_dropdown_btn_range = (0, 0, 0, 0)
        self._autostart_list_click_map.clear()
        self._kb_field_click_ranges.clear()
        self._kb_mod_chips.clear()
        self._kb_rec_btn_range = (0, 0, 0)
        self._kb_tab_click_ranges.clear()
        self._kb_app_dropdown_btn_range = (0, 0, 0, 0)
        self._kb_app_list_click_map.clear()

        if self.modal_state == "input_autostart":
            return self._render_autostart_modal(cols, rows)
        if self.modal_state in ("input_theme_hex", "input_creator_text"):
            return self._render_input_modal(cols, rows)
        if self.modal_state in ("edit_keybind", "add_keybind"):
            return self._render_keybind_modal(cols, rows)
        if self.modal_state == "record_compose":
            return self._render_compose_modal(cols, rows)

        if self.modal_state == "confirm_section_change":
            title = " CAMBIOS SIN APLICAR "
            msg_1 = "Hay cambios pendientes."
            msg_2 = "¿Aplicar antes de cambiar de seccion?"
            modal_btns = [
                (0, " Descartar "),
                (1, " Cancelar "),
                (2, " Aplicar "),
            ]
        elif self.modal_state == "confirm_delete_theme":
            t_slug = getattr(self, "_pending_delete_theme_slug", "")
            title = " BORRAR TEMA DE USUARIO "
            msg_1 = f"Se eliminara '{t_slug}' de tus temas."
            msg_2 = "¿Confirmar borrado?"
            modal_btns = [
                (0, " Cancelar "),
                (1, " Borrar "),
            ]
        else:
            title = " RESTABLECER "
            msg_1 = "Se restauraran los valores por defecto."
            msg_2 = "¿Continuar?"
            modal_btns = [
                (0, " Cancelar "),
                (1, " Confirmar "),
            ]

        mw = min(max(52, len(msg_2) + 8), cols - 4)
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

    def _render_keybind_modal(self, cols: int, rows: int) -> List[str]:
        """Renderiza el modal para editar o crear un atajo de teclado del sistema."""
        is_add = (self.modal_state == "add_keybind")
        title = " NUEVO ATAJO " if is_add else f" EDITAR ATAJO: {self.modal_kb_desc[:26]} "

        mw = min(70, cols - 4)
        inner_mw = mw - 2
        box_w = inner_mw - 6

        is_prog = (is_add and getattr(self, "modal_kb_tab", "program") == "program")
        filtered_apps = self._get_filtered_kb_apps() if is_prog else []
        list_rows = max(3, min(5, rows - 24)) if (is_prog and self.modal_kb_app_dropdown_open) else 0

        # Altura calculada dinámicamente según el modo y despliegue
        if not is_add:
            mh = 16
        elif is_prog:
            base_h = 24 if rows < 28 else 26
            mh = min(rows - 2, base_h + list_rows)
        else:
            base_h = 20 if rows < 28 else 22
            mh = min(rows - 2, base_h)

        start_x = max(2, (cols - mw) // 2)
        start_y = max(1, (rows - mh) // 2)

        overlay: List[str] = []
        top_line = "┌" + ("─" * inner_mw) + "┐"
        title_centered = title[:inner_mw].center(inner_mw)
        sep_line = "├" + ("─" * inner_mw) + "┤"
        bot_line = "┗" + ("━" * inner_mw) + "┙"

        overlay.append(f"\033[{start_y};{start_x}H" + self.theme_engine.style("bright_foreground", "background", top_line, bold=True))
        overlay.append(f"\033[{start_y + 1};{start_x}H" + self.theme_engine.style("bright_foreground", "accent", "┃" + title_centered + "│", bold=True))
        overlay.append(f"\033[{start_y + 2};{start_x}H" + self.theme_engine.style("muted", "background", sep_line))

        cur_y = start_y + 3

        if is_add:
            # ==========================================
            # PESTAÑAS SUPERIORES: PROGRAMA / COMANDO
            # ==========================================
            tab_prog_lbl = " [ 󰘳 Ejecutar Programa ] "
            tab_cmd_lbl = " [  Ejecutar Comando ] "
            is_t_prog = (self.modal_kb_tab == "program")
            is_t_cmd = (self.modal_kb_tab == "command")

            prog_hov = (getattr(self, "hover_kb_tab", None) == "program")
            cmd_hov = (getattr(self, "hover_kb_tab", None) == "command")

            prog_bg = "accent" if is_t_prog else ("soft_hover" if prog_hov else "background")
            prog_fg = "background" if is_t_prog else ("bright_foreground" if prog_hov else "muted")
            prog_styled = self.theme_engine.style(prog_fg, prog_bg, tab_prog_lbl, bold=(is_t_prog or prog_hov))

            cmd_bg = "accent" if is_t_cmd else ("soft_hover" if cmd_hov else "background")
            cmd_fg = "background" if is_t_cmd else ("bright_foreground" if cmd_hov else "muted")
            cmd_styled = self.theme_engine.style(cmd_fg, cmd_bg, tab_cmd_lbl, bold=(is_t_cmd or cmd_hov))

            gap_w = 2
            total_tabs_w = len(tab_prog_lbl) + gap_w + len(tab_cmd_lbl)
            pad_l = max(1, (inner_mw - total_tabs_w) // 2)
            pad_r = max(0, inner_mw - total_tabs_w - pad_l)

            t_prog_x1 = start_x + 1 + pad_l
            t_prog_x2 = t_prog_x1 + len(tab_prog_lbl) - 1
            t_cmd_x1 = t_prog_x2 + 1 + gap_w
            t_cmd_x2 = t_cmd_x1 + len(tab_cmd_lbl) - 1
            self._kb_tab_click_ranges["program"] = (cur_y, t_prog_x1, t_prog_x2)
            self._kb_tab_click_ranges["command"] = (cur_y, t_cmd_x1, t_cmd_x2)

            tab_line = (
                self.theme_engine.style("foreground", "background", "┃" + (" " * pad_l))
                + prog_styled
                + self.theme_engine.style("foreground", "background", " " * gap_w)
                + cmd_styled
                + self.theme_engine.style("foreground", "background", (" " * pad_r) + "│")
            )
            overlay.append(f"\033[{cur_y};{start_x}H" + tab_line)
            cur_y += 1
            overlay.append(f"\033[{cur_y};{start_x}H" + self.theme_engine.style("muted", "background", sep_line))
            cur_y += 1

        # ==========================================
        # CAMPO 0: COMBINACIÓN DE TECLAS Y CAPTURA
        # ==========================================
        is_f0_active = (self.modal_kb_field == 0)
        is_recording = getattr(self, "modal_kb_recording", False)

        # Fila 1: Etiqueta y Botón de Captura
        rec_btn_lbl = " [ 󰌌 Grabando... ] " if is_recording else " [ 󰌌 Capturar teclas ] "
        rec_btn_w = len(rec_btn_lbl)
        rec_btn_bg = "accent" if is_recording else ("soft_hover" if getattr(self, "hover_kb_rec", False) else "soft_selection")
        rec_btn_fg = "background" if is_recording else "bright_foreground"
        rec_btn_str = self.theme_engine.style(rec_btn_fg, rec_btn_bg, rec_btn_lbl, bold=True)

        lbl_keys = "  Combinación de teclas:"
        pad_gap = max(1, inner_mw - len(lbl_keys) - rec_btn_w)
        overlay.append(
            f"\033[{cur_y};{start_x}H"
            + self.theme_engine.style("foreground", "background", "┃")
            + self.theme_engine.style("muted", "background", lbl_keys + (" " * pad_gap))
            + rec_btn_str
            + self.theme_engine.style("foreground", "background", "│")
        )

        rec_x_start = start_x + 1 + len(lbl_keys) + pad_gap
        self._kb_rec_btn_range = (cur_y, rec_x_start, rec_x_start + rec_btn_w - 1)
        cur_y += 1

        # Fila 2: Modificadores interactivos (chips)
        chip_header = "  Modificadores: "
        chip_line_parts = [self.theme_engine.style("muted", "background", chip_header)]
        chip_cur_x = start_x + 1 + len(chip_header)
        plain_len = len(chip_header)
        current_mods_set = {m.strip().upper() for m in self.modal_kb_keys.split("+")}
        if is_recording:
            current_mods_set.update(getattr(self, "_kb_held_mods", set()))

        for mod in ("SUPER", "CTRL", "ALT", "SHIFT"):
            is_active = (mod in current_mods_set)
            is_hov = (getattr(self, "hover_kb_mod", None) == mod)
            chip_lbl = f"[{mod}]"
            chip_w = len(chip_lbl)
            chip_bg = "accent" if is_active else ("soft_hover" if is_hov else "background")
            chip_fg = "background" if is_active else ("bright_foreground" if is_hov else "muted")
            chip_styled = self.theme_engine.style(chip_fg, chip_bg, chip_lbl, bold=(is_active or is_hov))
            chip_line_parts.append(chip_styled + " ")
            self._kb_mod_chips[mod] = (cur_y, chip_cur_x, chip_cur_x + chip_w - 1)
            chip_cur_x += chip_w + 1
            plain_len += chip_w + 1

        chip_pad = max(0, inner_mw - plain_len)
        overlay.append(
            f"\033[{cur_y};{start_x}H"
            + self.theme_engine.style("foreground", "background", "┃")
            + "".join(chip_line_parts)
            + self.theme_engine.style("foreground", "background", (" " * chip_pad) + "│")
        )
        cur_y += 1

        # Filas 3..5: Caja de la combinación
        if is_recording:
            if self.modal_kb_keys.strip():
                shown_txt = f"󰌌 {self.modal_kb_keys.strip()} (suelta para guardar)"
            else:
                shown_txt = "󰌌 Presiona combinación (Esc: Cancelar)"
            f0_col = "accent"
            f0_txt_col = "bright_foreground"
            f0_bg = "soft_hover"
        else:
            val_txt = self.modal_kb_keys.strip()
            if not val_txt:
                shown_txt = "(Enter: Capturar │ 1:Super 2:Ctrl 3:Alt 4:Shift)"
                f0_txt_col = "muted"
            else:
                shown_txt = (val_txt + ("█" if is_f0_active else ""))
                f0_txt_col = "bright_foreground" if is_f0_active else "foreground"
            f0_col = "accent" if is_f0_active else "muted"
            f0_bg = "soft_selection" if is_f0_active else "background"

        shown_txt_pad = shown_txt[-box_w:].ljust(box_w)
        input0_top = ("  ┌" + ("─" * box_w) + "┐  ").ljust(inner_mw)[:inner_mw]
        input0_mid = f"  ┃{shown_txt_pad}│  ".ljust(inner_mw)[:inner_mw]
        input0_bot = ("  └" + ("─" * box_w) + "┘  ").ljust(inner_mw)[:inner_mw]

        self._kb_field_click_ranges[0] = (cur_y, cur_y + 2, start_x + 2, start_x + inner_mw - 2)

        overlay.append(f"\033[{cur_y};{start_x}H" + self.theme_engine.style(f0_col, "background", "┃" + input0_top + "│"))
        overlay.append(f"\033[{cur_y + 1};{start_x}H" + self.theme_engine.style(f0_txt_col, f0_bg, "┃" + input0_mid + "│", bold=(is_f0_active or is_recording)))
        overlay.append(f"\033[{cur_y + 2};{start_x}H" + self.theme_engine.style(f0_col, "background", "┃" + input0_bot + "│"))
        cur_y += 3

        # ==========================================
        # CAMPOS ESPECÍFICOS SEGÚN PESTAÑA / MODO
        # ==========================================
        if is_prog:
            # CAMPO 1: SELECTOR DESPLEGABLE DE PROGRAMAS DEL SISTEMA
            is_f1_active = (self.modal_kb_field == 1)
            arrow_char = "▴" if self.modal_kb_app_dropdown_open else "▾"
            if self.modal_kb_app_selected_name:
                dd_txt = f" {self.modal_kb_app_selected_name} ({self.modal_kb_app_selected_cmd})"
            elif filtered_apps and 0 <= self.modal_kb_app_idx < len(filtered_apps):
                cur_a = filtered_apps[self.modal_kb_app_idx]
                dd_txt = f" {cur_a['name']} — {cur_a['cmd']}"
            else:
                dd_txt = " Seleccionar programa del sistema..."

            if self.modal_kb_app_search.strip():
                dd_txt = f" [{self.modal_kb_app_search.strip()}]" + dd_txt

            dd_inner = (dd_txt[: box_w - 3].ljust(box_w - 3)) + f" {arrow_char} "
            dd_lbl = "  Programa del sistema:"

            dd_border_col = "accent" if (is_f1_active or self.modal_kb_app_dropdown_open) else "muted"
            dd_bg = "soft_hover" if self.modal_kb_app_dropdown_open else ("soft_selection" if is_f1_active else "background")
            dd_txt_col = "bright_foreground" if (is_f1_active or self.modal_kb_app_dropdown_open) else "foreground"

            dd_top = ("  ┌" + ("─" * box_w) + "┐  ").ljust(inner_mw)[:inner_mw]
            dd_mid = f"  ┃{dd_inner}│  ".ljust(inner_mw)[:inner_mw]
            dd_bot = ("  └" + ("─" * box_w) + "┘  ").ljust(inner_mw)[:inner_mw]

            self._kb_field_click_ranges[1] = (cur_y + 1, cur_y + 3, start_x + 2, start_x + inner_mw - 2)
            self._kb_app_dropdown_btn_range = (cur_y + 1, cur_y + 3, start_x + 2, start_x + inner_mw - 2)

            overlay.append(f"\033[{cur_y};{start_x}H" + self.theme_engine.style("muted", "background", "┃" + dd_lbl.ljust(inner_mw)[:inner_mw] + "│"))
            overlay.append(f"\033[{cur_y + 1};{start_x}H" + self.theme_engine.style(dd_border_col, "background", "┃" + dd_top + "│"))
            overlay.append(f"\033[{cur_y + 2};{start_x}H" + self.theme_engine.style(dd_txt_col, dd_bg, "┃" + dd_mid + "│", bold=(is_f1_active or self.modal_kb_app_dropdown_open)))
            overlay.append(f"\033[{cur_y + 3};{start_x}H" + self.theme_engine.style(dd_border_col, "background", "┃" + dd_bot + "│"))
            cur_y += 4

            if self.modal_kb_app_dropdown_open and list_rows > 0:
                if self.modal_kb_app_idx >= len(filtered_apps):
                    self.modal_kb_app_idx = max(0, len(filtered_apps) - 1)
                if self.modal_kb_app_idx < self.modal_kb_app_scroll:
                    self.modal_kb_app_scroll = self.modal_kb_app_idx
                elif self.modal_kb_app_idx >= self.modal_kb_app_scroll + list_rows:
                    self.modal_kb_app_scroll = self.modal_kb_app_idx - list_rows + 1
                self.modal_kb_app_scroll = max(0, min(self.modal_kb_app_scroll, max(0, len(filtered_apps) - list_rows)))

                self._kb_app_list_x_range = (start_x + 3, start_x + inner_mw - 3)
                for r_off in range(list_rows):
                    row_y = cur_y + r_off
                    f_idx = self.modal_kb_app_scroll + r_off
                    if f_idx < len(filtered_apps):
                        app = filtered_apps[f_idx]
                        self._kb_app_list_click_map[row_y] = f_idx
                        is_app_sel = (f_idx == self.modal_kb_app_idx)
                        is_app_hov = (f_idx == self.hover_kb_app_idx)
                        marker = " ▸ " if (is_app_sel or is_app_hov) else "   "
                        name_w = max(16, box_w - 24)
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

            prog_fields = [
                (2, "Comandos extras o argumentos (opcional):", self.modal_kb_app_extra),
                (3, "Nombre del atajo:", self.modal_kb_desc),
            ]
            for f_idx, f_lbl, f_val in prog_fields:
                is_f_active = (self.modal_kb_field == f_idx)
                shown_txt = ((f_val + "█") if is_f_active else f_val)[-box_w:].ljust(box_w)
                f_col = "accent" if is_f_active else "muted"
                f_txt_col = "bright_foreground" if is_f_active else "foreground"
                f_bg = "soft_selection" if is_f_active else "background"

                input_top = ("  ┌" + ("─" * box_w) + "┐  ").ljust(inner_mw)[:inner_mw]
                input_mid = f"  ┃{shown_txt}│  ".ljust(inner_mw)[:inner_mw]
                input_bot = ("  └" + ("─" * box_w) + "┘  ").ljust(inner_mw)[:inner_mw]

                self._kb_field_click_ranges[f_idx] = (cur_y + 1, cur_y + 3, start_x + 2, start_x + inner_mw - 2)

                overlay.append(f"\033[{cur_y};{start_x}H" + self.theme_engine.style("muted", "background", "┃  " + f_lbl.ljust(inner_mw - 2)[:inner_mw - 2] + "│"))
                overlay.append(f"\033[{cur_y + 1};{start_x}H" + self.theme_engine.style(f_col, "background", "┃" + input_top + "│"))
                overlay.append(f"\033[{cur_y + 2};{start_x}H" + self.theme_engine.style(f_txt_col, f_bg, "┃" + input_mid + "│", bold=is_f_active))
                overlay.append(f"\033[{cur_y + 3};{start_x}H" + self.theme_engine.style(f_col, "background", "┃" + input_bot + "│"))
                cur_y += 4
        else:
            other_fields = [(1, "Comando o accion:", self.modal_kb_action)]
            if is_add:
                other_fields.append((2, "Nombre del atajo:", self.modal_kb_desc))

            for f_idx, f_lbl, f_val in other_fields:
                is_f_active = (self.modal_kb_field == f_idx)
                shown_txt = ((f_val + "█") if is_f_active else f_val)[-box_w:].ljust(box_w)
                f_col = "accent" if is_f_active else "muted"
                f_txt_col = "bright_foreground" if is_f_active else "foreground"
                f_bg = "soft_selection" if is_f_active else "background"

                input_top = ("  ┌" + ("─" * box_w) + "┐  ").ljust(inner_mw)[:inner_mw]
                input_mid = f"  ┃{shown_txt}│  ".ljust(inner_mw)[:inner_mw]
                input_bot = ("  └" + ("─" * box_w) + "┘  ").ljust(inner_mw)[:inner_mw]

                self._kb_field_click_ranges[f_idx] = (cur_y + 1, cur_y + 3, start_x + 2, start_x + inner_mw - 2)

                overlay.append(f"\033[{cur_y};{start_x}H" + self.theme_engine.style("muted", "background", "┃  " + f_lbl.ljust(inner_mw - 2)[:inner_mw - 2] + "│"))
                overlay.append(f"\033[{cur_y + 1};{start_x}H" + self.theme_engine.style(f_col, "background", "┃" + input_top + "│"))
                overlay.append(f"\033[{cur_y + 2};{start_x}H" + self.theme_engine.style(f_txt_col, f_bg, "┃" + input_mid + "│", bold=is_f_active))
                overlay.append(f"\033[{cur_y + 3};{start_x}H" + self.theme_engine.style(f_col, "background", "┃" + input_bot + "│"))
                cur_y += 4

        # ==========================================
        # BOTONERA DEL MODAL
        # ==========================================
        modal_btns = [
            (0, " Cancelar "),
            (1, " Guardar "),
        ]
        if not is_add and 0 <= self.modal_kb_idx < len(self.keybind_items):
            entry = self.keybind_items[self.modal_kb_idx]
            is_en = bool(entry.get("enabled", True))
            modal_btns.append((2, " Desactivar " if is_en else " Activar "))

        gap = 2
        btns_total_w = sum(len(lbl) + 2 for _, lbl in modal_btns) + gap * (len(modal_btns) - 1)
        pad_left = max(1, (inner_mw - btns_total_w) // 2)
        pad_right = max(0, inner_mw - btns_total_w - pad_left)

        btn_y_top = cur_y
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
        overlay.append(f"\033[{btn_y_top + 3};{start_x}H" + self.theme_engine.style("accent", "background", bot_line, bold=True))
        return overlay

    def _render_autostart_modal(self, cols: int, rows: int) -> List[str]:
        """
        Renderiza el modal de Autostart con títulos cortos y directos.
        Cuando el selector de aplicación está deshabilitado (en modo Comando), solo se ve apagado.
        """
        is_app_mode = (self.modal_input_kind == "launch")
        if not is_app_mode:
            self.autostart_dropdown_open = False

        title = " AGREGAR A AUTOSTART "
        kind_val = "Aplicacion o servicio" if is_app_mode else "Comando"

        mw = min(62, cols - 4)
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

        selector_line = f"  Tipo: {kind_val} ▾".ljust(inner_mw)[:inner_mw]
        self._modal_kind_click_range = (start_y + 3, start_x + 2, start_x + inner_mw - 2)

        overlay.append(f"\033[{start_y};{start_x}H" + self.theme_engine.style("bright_foreground", "background", top_line, bold=True))
        overlay.append(f"\033[{start_y + 1};{start_x}H" + self.theme_engine.style("bright_foreground", "accent", "┃" + title_centered + "│", bold=True))
        overlay.append(f"\033[{start_y + 2};{start_x}H" + self.theme_engine.style("muted", "background", sep_line))
        overlay.append(f"\033[{start_y + 3};{start_x}H" + self.theme_engine.style("bright_foreground", "soft_selection", "┃" + selector_line + "│", bold=True))

        # Selector desplegable de aplicación (apagado cuando no está en modo aplicación, sin texto "deshabilitado")
        box_w = inner_mw - 6
        filtered = self._get_filtered_autostart_apps()
        arrow_char = "▴" if (is_app_mode and self.autostart_dropdown_open) else "▾"
        if self.autostart_selected_app_name and is_app_mode:
            dd_txt = f" {self.autostart_selected_app_name} ({self.modal_input_text})"
        elif filtered and 0 <= self.autostart_app_idx < len(filtered):
            cur_a = filtered[self.autostart_app_idx]
            dd_txt = f" {cur_a['name']} — {cur_a['cmd']}"
        else:
            dd_txt = " Seleccionar aplicacion..."
        dd_inner = (dd_txt[: box_w - 3].ljust(box_w - 3)) + f" {arrow_char} "
        dd_lbl = "  Seleccionar aplicacion:"

        if is_app_mode:
            dd_border_col = "accent" if self.autostart_dropdown_open else "bright_foreground"
            dd_bg = "soft_hover" if self.autostart_dropdown_open else "soft_selection"
            self._autostart_dropdown_btn_range = (start_y + 5, start_y + 6, start_x + 2, start_x + inner_mw - 2)
        else:
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

        # Campo de texto corto e intuitivo
        input_lbl = "  Aplicacion o comando:"
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

    def _render_input_modal(self, cols: int, rows: int) -> List[str]:
        """Renderiza la ventana modal interactiva para entrada de Color Hex (con previsualización) o texto."""
        is_hex_mode = (self.modal_state == "input_theme_hex")
        if is_hex_mode:
            title = " COLOR HEXADECIMAL "
            prop_name = self.modal_hex_target.replace("creator:", "")
            sub_lbl = f"  {prop_name}"
            prompt_lbl = "Codigo #RRGGBB:"
        else:
            title = " EDITAR VALOR "
            prop_name = self.modal_text_target.replace("creator:", "")
            sub_lbl = f"  {prop_name}"
            prompt_lbl = "Valor:"

        mw = min(58, cols - 4)
        inner_mw = mw - 2
        mh = 12
        start_x = max(2, (cols - mw) // 2)
        start_y = max(2, (rows - mh) // 2)

        overlay: List[str] = []
        top_line = "┌" + ("─" * inner_mw) + "┐"
        title_centered = title.center(inner_mw)[:inner_mw]
        sep_line = "├" + ("─" * inner_mw) + "┤"
        bot_line = "┗" + ("━" * inner_mw) + "┙"

        overlay.append(f"\033[{start_y};{start_x}H" + self.theme_engine.style("bright_foreground", "background", top_line, bold=True))
        overlay.append(f"\033[{start_y + 1};{start_x}H" + self.theme_engine.style("bright_foreground", "accent", "┃" + title_centered + "│", bold=True))
        overlay.append(f"\033[{start_y + 2};{start_x}H" + self.theme_engine.style("muted", "background", sep_line))

        if is_hex_mode:
            cand_hex = self.modal_input_text.strip()
            if not cand_hex.startswith("#"):
                cand_hex = "#" + cand_hex
            valid_hex = cand_hex if re.match(r"^#[0-9A-Fa-f]{6}$", cand_hex) else "#888888"
            r_c, g_c, b_c = self.theme_engine.hex_to_rgb(valid_hex)
            br, bg_v, bb = self.theme_engine.hex_to_rgb(self.theme_engine.colors.get("soft_selection", "#292e42"))
            swatch_seq = f"\033[48;2;{br};{bg_v};{bb}m\033[38;2;{r_c};{g_c};{b_c}m████\033[0m"
            prev_prefix = f"{sub_lbl}  │  "
            rem_w = max(1, inner_mw - len(prev_prefix) - 4)
            prev_suffix = f" {valid_hex}".ljust(rem_w)[:rem_w]
            line3 = (
                self.theme_engine.style("bright_foreground", "soft_selection", "┃" + prev_prefix, bold=True)
                + swatch_seq
                + self.theme_engine.style("bright_foreground", "soft_selection", prev_suffix + "│", bold=True)
            )
            overlay.append(f"\033[{start_y + 3};{start_x}H" + line3)
        else:
            selector_line = sub_lbl.ljust(inner_mw)[:inner_mw]
            overlay.append(f"\033[{start_y + 3};{start_x}H" + self.theme_engine.style("bright_foreground", "soft_selection", "┃" + selector_line + "│", bold=True))

        box_w = inner_mw - 6
        shown_txt = (self.modal_input_text + "█")[-box_w:].ljust(box_w)
        input_top = ("  ┌" + ("─" * box_w) + "┐  ").ljust(inner_mw)[:inner_mw]
        input_mid = f"  ┃{shown_txt}│  ".ljust(inner_mw)[:inner_mw]
        input_bot = ("  ┗" + ("━" * box_w) + "┙  ").ljust(inner_mw)[:inner_mw]

        overlay.append(f"\033[{start_y + 4};{start_x}H" + self.theme_engine.style("muted", "background", "┃" + f"  {prompt_lbl}".ljust(inner_mw)[:inner_mw] + "│"))
        overlay.append(f"\033[{start_y + 5};{start_x}H" + self.theme_engine.style("foreground", "background", "┃" + input_top + "│"))
        overlay.append(f"\033[{start_y + 6};{start_x}H" + self.theme_engine.style("bright_foreground", "background", "┃" + input_mid + "│", bold=True))
        overlay.append(f"\033[{start_y + 7};{start_x}H" + self.theme_engine.style("accent", "background", "┃" + input_bot + "│"))

        modal_btns = [
            (0, " Cancelar "),
            (1, " Guardar "),
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

    def _render_compose_modal(self, cols: int, rows: int) -> List[str]:
        """Renderiza la ventana modal interactiva para asignar tecla Compose física."""
        title = " ASIGNAR TECLA COMPOSE "
        mw = min(66, cols - 4)
        inner_mw = mw - 2
        start_x = max(2, (cols - mw) // 2)
        start_y = max(2, (rows - 15) // 2)

        overlay: List[str] = []
        top_line = "┌" + ("─" * inner_mw) + "┐"
        title_centered = title.center(inner_mw)[:inner_mw]
        sep_line = "├" + ("─" * inner_mw) + "┤"
        bot_line = "┗" + ("━" * inner_mw) + "┙"

        overlay.append(f"\033[{start_y};{start_x}H" + self.theme_engine.style("bright_foreground", "background", top_line, bold=True))
        overlay.append(f"\033[{start_y + 1};{start_x}H" + self.theme_engine.style("bright_foreground", "accent", "┃" + title_centered + "│", bold=True))
        overlay.append(f"\033[{start_y + 2};{start_x}H" + self.theme_engine.style("muted", "background", sep_line))

        lines = [
            "󰌌  Pulsa en tu teclado fisico la tecla para Compose:",
            "",
            " Teclas soportadas por XKB:",
            "   • Bloq Mayus (Caps Lock)    • Tecla Menu",
            "   • Super / Win Derecho       • Impr Pant (PrtSc)",
            "   • Insert / Pausa            • Scroll Lock",
            "   • Ctrl Derecho              • Ctrl Izquierdo",
            "",
            " [!] NOTA: Alt Gr NO se recomienda (desactiva el @)",
            "",
            " [Esc / Borrar]  Desactivar Compose (Recomendado)",
        ]

        for i, l in enumerate(lines):
            l_pad = f" {l}".ljust(inner_mw)[:inner_mw]
            if "[!]" in l:
                c_name = "error"
            elif "•" in l or "[Esc" in l:
                c_name = "bright_foreground"
            elif i == 0:
                c_name = "accent"
            else:
                c_name = "text"
            overlay.append(f"\033[{start_y + 3 + i};{start_x}H" + self.theme_engine.style(c_name, "background", "│" + l_pad + "│"))

        overlay.append(f"\033[{start_y + 3 + len(lines)};{start_x}H" + self.theme_engine.style("accent", "background", bot_line, bold=True))
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
        "cursor:theme": ("cursor_theme", str, "default"),
        "cursor:size": ("cursor_size", int, 24),
        "cursor:no_hardware_cursors": ("no_hw_cursors", bool, True),
        "cursor:inactive_timeout": ("cursor_timeout", int, 0),
        "cursor:hide_on_key_press": ("cursor_hide_on_key", bool, True),
        "cursor:hide_on_touch": ("cursor_hide_on_touch", bool, True),
        "cursor:warp_on_change_workspace": ("cursor_warp_workspace", int, 1),
        "cursor:zoom_factor": ("cursor_zoom", float, 1.0),
        "cursor:zoom_rigid": ("cursor_zoom_rigid", bool, False),
        # Keybinds & Input
        "input:kb_layout": ("kb_layout", str, "es"),
        "input:kb_variant": ("kb_variant", str, ""),
        "input:kb_model": ("kb_model", str, "pc105"),
        "input:kb_grp_toggle": ("kb_grp_toggle", str, "Ninguno"),
        "input:compose_key": ("compose_key", str, "none"),
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

        if key.startswith("creator:"):
            field = key.split(":", 1)[1]
            if field == "keyboard_rgb":
                raw_kb = str(self.theme_creator_spec.get("keyboard_rgb", "7aa2f7")).lstrip("#")[:6]
                return f"#{raw_kb}"
            return self.theme_creator_spec.get(field, "")

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

        if key == "cursor:theme":
            return str(self.settings.get("cursor_theme", "default") or "default")

        if key == "cursor:size":
            return str(self.settings.get("cursor_size", 24))

        if key == "input:kb_variant":
            v = str(self.settings.get("kb_variant", "")).strip()
            return v if v else "none"

        if key == "input:kb_model":
            m = str(self.settings.get("kb_model", "pc105")).strip()
            return m if m else "pc105"

        if key == "input:kb_grp_toggle":
            g = str(self.settings.get("kb_grp_toggle", "Ninguno")).strip()
            return g if g else "Ninguno"

        if key == "input:compose_key":
            ck = str(self.settings.get("compose_key", "none")).lower().strip()
            labels = {
                "none": "Desactivada (Recomendado para @)",
                "caps": "Bloq Mayús (Caps Lock)",
                "menu": "Tecla Menú",
                "rwin": "Super / Win Derecho",
                "lwin": "Super / Win Izquierdo",
                "prsc": "Impr Pant (PrtSc)",
                "ins": "Insert",
                "paus": "Pausa (Pause)",
                "sclk": "Bloq Despl (Scroll Lock)",
                "rctrl": "Ctrl Derecho",
                "lctrl": "Ctrl Izquierdo",
                "ralt": "Alt Gr (Desactiva @)",
            }
            return labels.get(ck, f"compose:{ck}" if ck not in ("", "none") else "Desactivada (Recomendado para @)")

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
        """Indica si el usuario modificó algún ajuste, autostart o atajo respecto al último estado aplicado."""
        return (
            (self.settings != self.saved_settings)
            or (self.autostart_items != self.saved_autostart)
            or (self.keybind_items != self.saved_keybinds)
        )

    def _open_search(self) -> None:
        """Abre el buscador global de configuraciones."""
        self.search_open = True
        self.search_query = ""
        self.search_scroll_offset = 0
        self.search_selected_idx = 0
        self.status_message = "Buscador global: Escribe para buscar... (Esc para salir)"
        self._perform_global_search()

    def _perform_global_search(self) -> None:
        """Filtra todos los items de todas las secciones principales (excluyendo CREATOR_SECTIONS y headers)."""
        self.search_results.clear()
        query = self.search_query.lower().strip()
        
        for sec_idx, sec_meta in enumerate(self.SECTIONS):
            sec_id = sec_meta[1]
            sec_title = sec_meta[3]
            
            items = self.section_items.get(sec_id, [])
            for item_idx, item in enumerate(items):
                if item.item_type == "header":
                    continue
                    
                match = False
                if not query:
                    match = True
                else:
                    haystack = f"{item.name} {item.desc} {sec_title}".lower()
                    if query in haystack:
                        match = True
                        
                if match:
                    self.search_results.append((sec_idx, item_idx, item))
                    
        if self.search_selected_idx >= len(self.search_results):
            self.search_selected_idx = max(0, len(self.search_results) - 1)
        self.search_scroll_offset = 0

    def _navigate_to_search_result(self, exec_action: bool = False) -> None:
        """Navega a la sección del resultado seleccionado y opcionalmente edita en línea."""
        if not self.search_results or not (0 <= self.search_selected_idx < len(self.search_results)):
            return
            
        sec_idx, item_idx, item = self.search_results[self.search_selected_idx]
        self.search_open = False
        
        self.view_mode = "main"
        self.current_section_idx = sec_idx
        self.selected_item_idx = item_idx
        self.active_pane = "content"
        self.content_scroll_offset = max(0, item_idx - 2)
        
        if exec_action:
            self._activate_current_item()
        else:
            self.status_message = f"Resultado: {item.name}"

    def _render_search_overlay(self, cols: int, rows: int) -> List[str]:
        """Renderiza el modal flotante tipo spotlight del buscador."""
        self._search_click_map.clear()
        self._search_box_bounds = (0, 0, 0, 0)
        
        mw = min(max(52, 62), cols - 6)
        mh = min(rows - 6, 22)
        inner_mw = mw - 2
        start_x = max(2, (cols - mw) // 2)
        start_y = max(3, (rows - mh) // 2)
        self._search_box_bounds = (start_y, start_y + mh - 1, start_x, start_x + mw - 1)
        
        overlay: List[str] = []
        
        top_line = "┌" + ("─" * inner_mw) + "┐"
        title = " 󰍉 BUSCAR CONFIGURACIÓN "
        title_centered = title.ljust(inner_mw, "─")[:inner_mw]
        overlay.append(f"\033[{start_y};{start_x}H" + self.theme_engine.style("bright_foreground", "accent", "┌" + title_centered + "┐", bold=True))
        
        q_display = self.search_query + "▌"
        if len(q_display) > inner_mw - 2:
            q_display = "..." + q_display[-(inner_mw - 5):]
        q_line = " " + q_display.ljust(inner_mw - 1)
        overlay.append(f"\033[{start_y + 1};{start_x}H" + self.theme_engine.style("bright_foreground", "background", "┃" + q_line + "│", bold=True))
        overlay.append(f"\033[{start_y + 2};{start_x}H" + self.theme_engine.style("muted", "background", "├" + ("─" * inner_mw) + "┤"))
        
        res_area_h = mh - 5
        max_visible = res_area_h // 2
        
        if self.search_selected_idx < self.search_scroll_offset:
            self.search_scroll_offset = self.search_selected_idx
        elif self.search_selected_idx >= self.search_scroll_offset + max_visible:
            self.search_scroll_offset = self.search_selected_idx - max_visible + 1
            
        cur_y = start_y + 3
        visible_end = min(len(self.search_results), self.search_scroll_offset + max_visible)
        
        if not self.search_results:
            msg = "Sin resultados".center(inner_mw)
            overlay.append(f"\033[{cur_y};{start_x}H" + self.theme_engine.style("muted", "background", "┃" + msg + "│"))
            overlay.append(f"\033[{cur_y + 1};{start_x}H" + self.theme_engine.style("muted", "background", "┃" + (" " * inner_mw) + "│"))
            cur_y += 2
        else:
            for i in range(self.search_scroll_offset, visible_end):
                sec_idx, item_idx, item = self.search_results[i]
                sec_title = self.SECTIONS[sec_idx][3]
                
                is_hov = (i == getattr(self, "hover_search_idx", None))
                is_sel = (i == self.search_selected_idx) or is_hov
                
                self._search_click_map[cur_y] = i
                self._search_click_map[cur_y + 1] = i
                
                name_w = inner_mw - len(sec_title) - 4
                if name_w < 5:
                    name_w = 5
                
                n_txt = item.name[:name_w].ljust(name_w)
                s_txt = sec_title.rjust(inner_mw - name_w - 3)
                
                if is_sel:
                    l1_s = self.theme_engine.style("bright_foreground", "soft_selection", f" ▌ {n_txt}", bold=True) + self.theme_engine.style("muted", "soft_selection", f"{s_txt} ")
                    l2_s = self.theme_engine.style("foreground", "soft_selection", f"   {item.desc}"[:inner_mw].ljust(inner_mw))
                else:
                    l1_s = self.theme_engine.style("bright_foreground", "background", f"   {n_txt}") + self.theme_engine.style("muted", "background", f"{s_txt} ")
                    l2_s = self.theme_engine.style("muted", "background", f"   {item.desc}"[:inner_mw].ljust(inner_mw))
                    
                overlay.append(f"\033[{cur_y};{start_x}H" + self.theme_engine.style("foreground", "background", "┃") + l1_s + self.theme_engine.style("foreground", "background", "│"))
                overlay.append(f"\033[{cur_y + 1};{start_x}H" + self.theme_engine.style("foreground", "background", "┃") + l2_s + self.theme_engine.style("foreground", "background", "│"))
                cur_y += 2
                
        while cur_y < start_y + mh - 2:
            overlay.append(f"\033[{cur_y};{start_x}H" + self.theme_engine.style("muted", "background", "┃" + (" " * inner_mw) + "│"))
            cur_y += 1
            
        overlay.append(f"\033[{start_y + mh - 2};{start_x}H" + self.theme_engine.style("muted", "background", "├" + ("─" * inner_mw) + "┤"))
        keys_hint = " Enter: Ir │ Espacio/Tab: Editar │ Esc: Cerrar "
        keys_centered = keys_hint.center(inner_mw)[:inner_mw]
        overlay.append(f"\033[{start_y + mh - 1};{start_x}H" + self.theme_engine.style("accent", "background", "┗" + keys_centered.replace(" ", "━") + "┙", bold=True))
        
        return overlay

    def _request_section_change(self, target_idx: int, focus_content: bool = False) -> None:
        """
        Cambia a la sección 'target_idx' de la barra lateral izquierda.
        En la ventana principal, si existen cambios sin aplicar, abre la confirmación.
        En la ventana de creación de temas, cambia directamente entre las categorías del estudio.
        """
        self.dropdown_open = False
        self.context_menu_open = False
        active_sections = self._get_active_sections()
        target_idx = max(0, min(len(active_sections) - 1, target_idx))
        if target_idx == self.current_section_idx:
            if focus_content:
                self.active_pane = "content"
            return

        if self.view_mode == "main" and self.has_unsaved_changes():
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

    def _open_keybind_modal(self, kb_idx: int, initial_field: int = 0) -> None:
        """Abre el modal de edición de un atajo de teclado del sistema."""
        if not (0 <= kb_idx < len(self.keybind_items)):
            return
        entry = self.keybind_items[kb_idx]
        self.modal_state = "edit_keybind"
        self.modal_kb_idx = kb_idx
        self.modal_kb_field = initial_field
        self.modal_kb_keys = str(entry.get("keys", ""))
        self.modal_kb_action = str(entry.get("cmd", ""))
        self.modal_kb_desc = str(entry.get("title", ""))
        self.modal_selected_idx = 1
        self.modal_kb_recording = False

    def _start_keybind_recording(self) -> None:
        """Activa el modo de escucha interactiva de atajos de teclado y el submap en Hyprland."""
        self.modal_kb_recording = True
        self._kb_held_mods.clear()
        self._kb_currently_pressed.clear()
        self._kb_last_combo = ""
        self._kb_captured_ready = False

        if os.path.exists(self._rec_file):
            try:
                os.remove(self._rec_file)
            except Exception:
                pass

        self._kb_held_mods.clear()
        self._kb_currently_pressed.clear()
        self._kb_captured_ready = False
        self._kb_last_combo = ""
        self.modal_kb_keys = "..."
        self.status_message = "󰌌  Presiona combinación de teclas (suelta la 1ª tecla para guardar)..."
        try:
            sys.stdout.write("\033[>31u")
            sys.stdout.flush()
        except Exception:
            pass

        lua_rec = f"""
_G.__meca_rec_active = true
_G.__meca_first_key = nil
_G.__meca_held = {{}}
_G.__meca_all_pressed = {{}}
_G.__meca_done = false
_G.__meca_file = "{self._rec_file}"

local function write_state()
    local held_arr = {{}}
    for k, v in pairs(_G.__meca_held or {{}}) do
        if v then table.insert(held_arr, k) end
    end
    local all_arr = {{}}
    for k, v in pairs(_G.__meca_all_pressed or {{}}) do
        if v then table.insert(all_arr, k) end
    end
    local f = io.open(_G.__meca_file, "w")
    if f then
        f:write(string.format('{{"active":%s,"done":%s,"first":%s,"held":[%s],"all":[%s]}}',
            _G.__meca_rec_active and "true" or "false",
            _G.__meca_done and "true" or "false",
            _G.__meca_first_key and tostring(_G.__meca_first_key) or "null",
            table.concat(held_arr, ","),
            table.concat(all_arr, ",")
        ))
        f:close()
    end
end

_G.__meca_key_callback = function(keycode, time_ms, state)
    if _G.__meca_compose_rec and _G.__meca_compose_callback then
        _G.__meca_compose_callback(keycode, time_ms, state)
        return
    end
    if not _G.__meca_rec_active then return end
    if keycode == 0 then return end
    if state == 1 then
        if _G.__meca_first_key == nil then
            _G.__meca_first_key = keycode
            _G.__meca_all_pressed = {{}}
            _G.__meca_held = {{}}
        end
        _G.__meca_held[keycode] = true
        _G.__meca_all_pressed[keycode] = true
        write_state()
    elseif state == 0 then
        _G.__meca_held[keycode] = nil
        local count_held = 0
        for _ in pairs(_G.__meca_held or {{}}) do count_held = count_held + 1 end
        if _G.__meca_first_key ~= nil and (keycode == _G.__meca_first_key or count_held == 0) then
            _G.__meca_done = true
            _G.__meca_rec_active = false
            write_state()
        else
            write_state()
        end
    end
end

write_state()

if not _G.__meca_hook_installed then
    _G.__meca_hook_installed = true
    hl.on("input.keyboard.key", function(keycode, time_ms, state)
        if _G.__meca_key_callback then
            _G.__meca_key_callback(keycode, time_ms, state)
        end
    end)
end

hl.define_submap("meca_rec", function() hl.bind("escape", hl.dsp.submap("reset")) end)
hl.dispatch(hl.dsp.submap("meca_rec"))
"""
        try:
            res = HyprIPC.eval(lua_rec)
            self._hypr_rec_active = (res is not None)
        except Exception:
            self._hypr_rec_active = False

    def _stop_keybind_recording(self) -> None:
        """Desactiva el modo de escucha interactiva y restaura el submap en Hyprland."""
        self.modal_kb_recording = False
        self._hypr_rec_active = False
        self._last_recording_finish_time = time.time()
        self._kb_held_mods.clear()
        self._kb_currently_pressed.clear()
        self._kb_captured_ready = False
        try:
            sys.stdout.write("\033[<1u")
            sys.stdout.flush()
        except Exception:
            pass
        try:
            HyprIPC.eval('_G.__meca_rec_active = false; hl.dispatch(hl.dsp.submap("reset"))')
        except Exception:
            pass
        if os.path.exists(self._rec_file):
            try:
                os.remove(self._rec_file)
            except Exception:
                pass
        try:
            import termios
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        except Exception:
            pass

    def _start_compose_recording(self) -> None:
        """Inicia el modo interactivo para asignar una tecla Compose física."""
        self.modal_state = "record_compose"
        if os.path.exists(self._compose_rec_file):
            try:
                os.remove(self._compose_rec_file)
            except Exception:
                pass
        self.status_message = "󰌌  Pulsa la tecla física para Compose (Esc para cancelar/desactivar)..."

        lua_comp = f"""
_G.__meca_compose_rec = true
_G.__meca_compose_file = "{self._compose_rec_file}"

_G.__meca_compose_callback = function(keycode, time_ms, state)
    if not _G.__meca_compose_rec then return end
    if state == 1 and keycode > 0 then
        _G.__meca_compose_rec = false
        local f = io.open(_G.__meca_compose_file, "w")
        if f then
            f:write(string.format('{{"code":%d}}', keycode))
            f:close()
        end
    end
end

if not _G.__meca_hook_installed then
    _G.__meca_hook_installed = true
    hl.on("input.keyboard.key", function(keycode, time_ms, state)
        if _G.__meca_compose_rec and _G.__meca_compose_callback then
            _G.__meca_compose_callback(keycode, time_ms, state)
        elseif _G.__meca_key_callback then
            _G.__meca_key_callback(keycode, time_ms, state)
        end
    end)
end

hl.define_submap("meca_comp_rec", function() hl.bind("escape", hl.dsp.submap("reset")) end)
hl.dispatch(hl.dsp.submap("meca_comp_rec"))
"""
        try:
            HyprIPC.eval(lua_comp)
        except Exception:
            pass

    def _stop_compose_recording(self) -> None:
        """Desactiva la escucha de tecla Compose interactiva."""
        try:
            HyprIPC.eval('_G.__meca_compose_rec = false; hl.dispatch(hl.dsp.submap("reset"))')
        except Exception:
            pass
        if hasattr(self, "_compose_rec_file") and os.path.exists(self._compose_rec_file):
            try:
                os.remove(self._compose_rec_file)
            except Exception:
                pass

    def _apply_compose_choice(self, compose_key: str, key_name: str) -> None:
        """Aplica la tecla Compose seleccionada por el usuario."""
        self._stop_compose_recording()
        self.modal_state = None
        self.settings["compose_key"] = compose_key
        self.saved_settings["compose_key"] = compose_key
        self.config_sync.fix_caps_lock(compose_key=compose_key)
        self.config_sync.save_gui_settings(self.settings, apply_live=True)
        self.status_message = f"✓ Tecla Compose asignada a: {key_name}"

    def _check_compose_recording(self) -> bool:
        """Comprueba si Hyprland capturó la tecla para Compose."""
        if self.modal_state != "record_compose":
            return False
        if hasattr(self, "_compose_rec_file") and os.path.exists(self._compose_rec_file):
            try:
                with open(self._compose_rec_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                code = data.get("code")
                if code:
                    if code in (9, 22):
                        self._apply_compose_choice("none", "Desactivada (Recomendado)")
                        return True
                    if code in self.COMPOSE_KEY_MAP:
                        c_id, c_lbl = self.COMPOSE_KEY_MAP[code]
                        self._apply_compose_choice(c_id, c_lbl)
                        return True
                    else:
                        key_sym = self.xkb_key_map.get(code, f"Code_{code}")
                        self.status_message = f"Tecla '{key_sym}' no admitida por XKB Compose. Usa Caps, Menú, Win, PrtSc..."
                        self._stop_compose_recording()
                        self.modal_state = None
                        return True
            except Exception:
                pass
        return False

    def _check_hyprland_keybind_recording(self) -> bool:
        """Lee el estado del capturador de teclado en tiempo real desde Hyprland. Retorna True si la captura finalizo o se cancelo."""
        if not getattr(self, "modal_kb_recording", False):
            return False
        if not os.path.exists(self._rec_file):
            return False
        try:
            with open(self._rec_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False

        all_codes = data.get("all", [])
        first_code = data.get("first")
        is_done = bool(data.get("done", False))

        # Si el usuario presiono Escape como primera tecla, cancelar
        if first_code == 9 and len(all_codes) == 1:
            self._stop_keybind_recording()
            self.status_message = "Captura de atajo cancelada."
            return True

        if not all_codes:
            return False

        key_names = [self.xkb_key_map.get(c, f"KEY_{c}") for c in all_codes]
        combo = self._normalize_keybind_string(" + ".join(key_names))

        if is_done:
            self.modal_kb_keys = combo
            self._stop_keybind_recording()
            self.status_message = f"✓ Atajo capturado: {combo} (Pulsa Enter en Guardar)"
            max_field = self._get_keybind_max_field()
            self.modal_kb_field = max_field + 1
            self.modal_selected_idx = 1
            return True
        else:
            self.modal_kb_keys = combo + " ..."
            self.status_message = f"󰌌  {combo} detectado... suelta la primera tecla para guardar"
            return False

    @classmethod
    def _codepoint_to_key_name(cls, cp: int) -> str:
        """Mapea un codepoint del protocolo Kitty a nombre canonico de tecla para Hyprland."""
        if cp in cls.SPECIAL_CODEPOINTS:
            return cls.SPECIAL_CODEPOINTS[cp]
        if 33 <= cp <= 126:
            char = chr(cp).upper()
            char_map = {
                ",": "comma", ".": "period", "/": "slash", "-": "MINUS", "=": "EQUAL",
                ";": "SEMICOLON", "'": "APOSTROPHE", "`": "GRAVE", "\\": "BACKSLASH",
                "[": "BRACKETLEFT", "]": "BRACKETRIGHT"
            }
            return char_map.get(char, char)
        return f"KEY_{cp}"

    def _handle_keybind_recording_input(self, ch: bytes) -> bool:
        """
        Gestiona la captura interactiva en tiempo real.
        - Mantiene la acumulacion de modificadores y teclas mientras se presionan.
        - Actualiza la previsualizacion en vivo.
        - Soporta combinaciones complejas como SUPER + CTRL + M, Impr pant, etc.
        """
        # Esc solo (sin modificadores) cancela la grabacion
        if ch == b"\x1b" and len(ch) == 1:
            self._stop_keybind_recording()
            self.status_message = "Captura de atajo cancelada."
            return True

        # 1. Comprobar secuencias Kitty keyboard protocol: \x1b[ <codepoint> [;<modifiers>] [:<event>] u
        kitty_pattern = rb"\x1b\[(\d+)(?:;(\d+))?(?::(\d+))?u"
        kitty_matches = list(re.finditer(kitty_pattern, ch))

        if kitty_matches:
            for m in kitty_matches:
                codepoint = int(m.group(1))
                mod_mask = int(m.group(2) or 1) - 1
                event = int(m.group(3) or 1)  # 1: press, 2: repeat, 3: release

                kitty_mods = set()
                if mod_mask & 8: kitty_mods.add("SUPER")
                if mod_mask & 4: kitty_mods.add("CTRL")
                if mod_mask & 2: kitty_mods.add("ALT")
                if mod_mask & 1: kitty_mods.add("SHIFT")

                is_mod = codepoint in self.KITTY_MOD_MAP
                mod_name = self.KITTY_MOD_MAP.get(codepoint)

                if is_mod:
                    if event in (1, 2):
                        self._kb_currently_pressed.add(codepoint)
                        if mod_name:
                            self._kb_held_mods.add(mod_name)
                        self._kb_held_mods.update(kitty_mods)
                        mods_order = [mod for mod in ("SUPER", "CTRL", "ALT", "SHIFT") if mod in self._kb_held_mods]
                        self.modal_kb_keys = " + ".join(mods_order + ["..."])
                        self.status_message = f"󰌌  {' + '.join(mods_order)} presionado... presiona la siguiente tecla"
                    elif event == 3:
                        self._kb_currently_pressed.discard(codepoint)
                        if mod_name:
                            self._kb_held_mods.discard(mod_name)
                        if self._kb_captured_ready and self._kb_last_combo:
                            if len(self._kb_currently_pressed) == 0:
                                self.modal_kb_keys = self._kb_last_combo
                                self._stop_keybind_recording()
                                self.status_message = f"✓ Atajo capturado: {self.modal_kb_keys} (Pulsa Enter en Guardar)"
                                max_field = self._get_keybind_max_field()
                                self.modal_kb_field = max_field + 1
                                self.modal_selected_idx = 1
                                return True
                        else:
                            if len(self._kb_currently_pressed) == 0 and mod_name:
                                self.modal_kb_keys = mod_name
                                self._stop_keybind_recording()
                                self.status_message = f"✓ Atajo capturado: {self.modal_kb_keys} (Pulsa Enter en Guardar)"
                                max_field = self._get_keybind_max_field()
                                self.modal_kb_field = max_field + 1
                                self.modal_selected_idx = 1
                                return True
                            mods_order = [mod for mod in ("SUPER", "CTRL", "ALT", "SHIFT") if mod in self._kb_held_mods]
                            self.modal_kb_keys = (" + ".join(mods_order + ["..."])) if mods_order else ""
                else:
                    # Tecla principal (M, RETURN, SPACE, PRINT, etc.)
                    if event in (1, 2):
                        if codepoint == 27 and not kitty_mods and not self._kb_held_mods:
                            self._stop_keybind_recording()
                            self.status_message = "Captura de atajo cancelada."
                            return True

                        self._kb_currently_pressed.add(codepoint)
                        all_mods = set(kitty_mods) | self._kb_held_mods
                        key_name = self._codepoint_to_key_name(codepoint)
                        combo = self._normalize_keybind_string(" + ".join(list(all_mods) + [key_name]))

                        self._kb_last_combo = combo
                        self._kb_captured_ready = True
                        self.modal_kb_keys = combo
                        self.status_message = f"󰌌  {combo} detectado. Suelta las teclas para guardar..."
                    elif event == 3:
                        self._kb_currently_pressed.discard(codepoint)
                        if self._kb_captured_ready and self._kb_last_combo:
                            if len(self._kb_currently_pressed) == 0:
                                self.modal_kb_keys = self._kb_last_combo
                                self._stop_keybind_recording()
                                self.status_message = f"✓ Atajo capturado: {self.modal_kb_keys} (Pulsa Enter en Guardar)"
                                max_field = self._get_keybind_max_field()
                                self.modal_kb_field = max_field + 1
                                self.modal_selected_idx = 1
                                return True
                            else:
                                self.modal_kb_keys = self._kb_last_combo
                                self.status_message = f"󰌌  {self._kb_last_combo} capturado. Suelta las teclas restantes..."
            return True

        # 2. Fallback para terminales o secuencias sin protocolo Kitty (ANSI clasico)
        combo = self._parse_key_combination(ch)
        if combo:
            parts = [p.strip().upper() for p in combo.split("+") if p.strip()]
            det_mods = [m for m in ("SUPER", "CTRL", "ALT", "SHIFT") if m in parts]
            main_keys = [k for k in parts if k not in ("SUPER", "CTRL", "ALT", "SHIFT")]

            all_mods = set(self._kb_held_mods) | set(det_mods)
            ordered_mods = [m for m in ("SUPER", "CTRL", "ALT", "SHIFT") if m in all_mods]

            if main_keys:
                final_combo = " + ".join(ordered_mods + main_keys)
            elif ordered_mods:
                final_combo = " + ".join(ordered_mods)
            else:
                final_combo = combo

            final_combo = self._normalize_keybind_string(final_combo)
            self.modal_kb_keys = final_combo
            self._stop_keybind_recording()
            self.status_message = f"✓ Atajo capturado: {final_combo} (Pulsa Enter en Guardar)"
            max_field = self._get_keybind_max_field()
            self.modal_kb_field = max_field + 1
            self.modal_selected_idx = 1
            return True

        return True

    def _toggle_kb_modifier(self, mod: str) -> None:
        """Alterna un modificador (SUPER, CTRL, ALT, SHIFT) en la combinación del modal."""
        mod = mod.upper().strip()
        all_mods = ["SUPER", "CTRL", "ALT", "SHIFT"]
        norm = self._normalize_keybind_string(self.modal_kb_keys)
        parts = [p.strip().upper() for p in norm.split("+") if p.strip()]
        active_mods = [m for m in all_mods if m in parts]
        main_keys = [k for k in parts if k not in all_mods]

        if mod in active_mods:
            active_mods.remove(mod)
        else:
            active_mods.append(mod)
            active_mods = [m for m in all_mods if m in active_mods]

        if getattr(self, "modal_kb_recording", False):
            self._kb_held_mods = set(active_mods)
            if main_keys:
                self.modal_kb_keys = " + ".join(active_mods + main_keys)
            elif active_mods:
                self.modal_kb_keys = " + ".join(active_mods + ["..."])
            else:
                self.modal_kb_keys = ""
        else:
            if active_mods or main_keys:
                self.modal_kb_keys = " + ".join(active_mods + main_keys)
            else:
                self.modal_kb_keys = ""
        self.status_message = f"Atajo: {self.modal_kb_keys}"

    def _parse_key_combination(self, data: bytes) -> str:
        """Interpreta secuencias de terminal (Kitty protocol, CSI, SS3, ANSI) como combinaciones de teclas legibles."""
        if not data:
            return ""

        # 1. Kitty keyboard protocol: \x1b[ <codepoint> ; <modifier> [: <event>] u
        m = re.match(rb"^\x1b\[(\d+)(?:;(\d+))?(?::(\d+))?u$", data)
        if m:
            codepoint = int(m.group(1))
            mod_mask = int(m.group(2) or 1) - 1
            event = int(m.group(3) or 1)
            if event == 3 or codepoint in self.KITTY_MOD_MAP:
                return ""
            mods = []
            if mod_mask & 8: mods.append("SUPER")
            if mod_mask & 4: mods.append("CTRL")
            if mod_mask & 2: mods.append("ALT")
            if mod_mask & 1: mods.append("SHIFT")
            key_name = self._codepoint_to_key_name(codepoint)
            return " + ".join(mods + [key_name])

        # 2. Secuencias directas exactas (navegación, Print Screen / Impr Pant, F1-F4)
        plain_nav = {
            b"\x1b[A": "UP", b"\x1b[B": "DOWN", b"\x1b[C": "RIGHT", b"\x1b[D": "LEFT",
            b"\x1b[H": "HOME", b"\x1b[F": "END",
            b"\x1b[2~": "INSERT", b"\x1b[3~": "DELETE", b"\x1b[5~": "PAGE_UP", b"\x1b[6~": "PAGE_DOWN",
            b"\x1b[19~": "PRINT", b"\x1b[20~": "PRINT", b"\x1b[32~": "PRINT", b"\x1b[57362~": "PRINT",
            b"\x1b[1;2P": "SHIFT + PRINT", b"\x1b[1;3P": "ALT + PRINT", b"\x1b[1;5P": "CTRL + PRINT",
            b"\x1b[1;6P": "CTRL + SHIFT + PRINT", b"\x1b[1;9P": "SUPER + PRINT",
            b"\x1b[1;13P": "SUPER + CTRL + PRINT",
            b"\x1bOP": "F1", b"\x1bOQ": "F2", b"\x1bOR": "F3", b"\x1bOS": "F4",
            b"\x1b[Z": "SHIFT + TAB",
        }
        if data in plain_nav:
            return plain_nav[data]

        # 3. CSI con modificador: \x1b[ 1 ; <mod> <A|B|C|D|H|F> o \x1b[ 1 ; <mod> <P|Q|R|S>
        m = re.match(rb"^\x1b\[(?:1;)?(\d+)([ABCDHFPQRS])$", data)
        if m:
            mod_mask = int(m.group(1)) - 1
            d = m.group(2).decode("ascii", errors="ignore")
            dirs = {
                "A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT", "H": "HOME", "F": "END",
                "P": "F1", "Q": "F2", "R": "F3", "S": "F4"
            }
            mods = []
            if mod_mask & 8: mods.append("SUPER")
            if mod_mask & 4: mods.append("CTRL")
            if mod_mask & 2: mods.append("ALT")
            if mod_mask & 1: mods.append("SHIFT")
            return " + ".join(mods + [dirs.get(d, d)])

        # 4. CSI tilde con modificador: \x1b[ <num> ; <mod> ~
        m = re.match(rb"^\x1b\[(\d+)(?:;(\d+))?~$", data)
        if m:
            num = int(m.group(1))
            mod_mask = int(m.group(2) or 1) - 1
            num_keys = {
                2: "INSERT", 3: "DELETE", 5: "PAGE_UP", 6: "PAGE_DOWN",
                15: "F5", 17: "F6", 18: "F7", 19: "PRINT", 20: "PRINT", 21: "F10", 23: "F11", 24: "F12",
                32: "PRINT", 57362: "PRINT"
            }
            if num in num_keys:
                mods = []
                if mod_mask & 8: mods.append("SUPER")
                if mod_mask & 4: mods.append("CTRL")
                if mod_mask & 2: mods.append("ALT")
                if mod_mask & 1: mods.append("SHIFT")
                return " + ".join(mods + [num_keys[num]])

        # 7. Alt + tecla (\x1b + char)
        if len(data) == 2 and data[0] == 0x1B:
            c = data[1]
            if c in (10, 13):
                return "ALT + RETURN"
            if c == 0x20:
                return "ALT + SPACE"
            if c in (0x7F, 0x08):
                return "ALT + BACKSPACE"
            if c == 0x09:
                return "ALT + TAB"
            if 1 <= c <= 26:
                return f"CTRL + ALT + {chr(c + 64)}"
            if 32 <= c <= 126:
                ch_raw = chr(c).upper()
                char_map = {
                    ",": "comma", ".": "period", "/": "slash", "-": "MINUS", "=": "EQUAL",
                    ";": "SEMICOLON", "'": "APOSTROPHE", "`": "GRAVE", "\\": "BACKSLASH",
                    "[": "BRACKETLEFT", "]": "BRACKETRIGHT"
                }
                return f"ALT + {char_map.get(ch_raw, ch_raw)}"

        # 8. Carácter de control o tecla simple
        if len(data) == 1:
            b = data[0]
            if b == 0:
                return "CTRL + SPACE"
            if 1 <= b <= 26:
                if b == 9: return "TAB"
                if b in (10, 13):
                    # Si CTRL está activo o ya seleccionado, se interpreta como la letra M o J
                    if getattr(self, "modal_kb_recording", False) and "CTRL" in getattr(self, "_kb_held_mods", set()):
                        return "M" if b == 13 else "J"
                    return "CTRL + M" if b == 13 else "CTRL + J"
                return f"CTRL + {chr(b + 64)}"
            if b in (0x7F, 0x08):
                return "BACKSPACE"
            if b == 0x1B:
                return "ESCAPE"
            if b == 0x20:
                return "SPACE"
            if 33 <= b <= 126:
                ch_char = chr(b).upper()
                char_map = {
                    ",": "comma", ".": "period", "/": "slash", "-": "MINUS", "=": "EQUAL",
                    ";": "SEMICOLON", "'": "APOSTROPHE", "`": "GRAVE", "\\": "BACKSLASH",
                    "[": "BRACKETLEFT", "]": "BRACKETRIGHT"
                }
                return char_map.get(ch_char, ch_char)

        return ""

    def _open_theme_editor(self, theme_name: str) -> None:
        """Abre el Estudio de Temas precargado con el tema indicado para editarlo."""
        self._prev_main_section_idx = self.current_section_idx
        slug = self.theme_engine.normalize_theme_slug(theme_name)
        self.theme_creator_spec = self.theme_engine.get_theme_full_spec(theme_name)
        self.theme_creator_spec["name"] = slug
        self.theme_creator_spec["base_theme"] = theme_name
        self.creator_is_editing = True
        self.creator_editing_slug = slug
        for _, c_sec_id, _, _, _ in self.CREATOR_SECTIONS:
            self.section_items[c_sec_id] = self._build_creator_section_items(c_sec_id)
        self.view_mode = "theme_creator"
        self.current_section_idx = 0
        self.selected_item_idx = 1
        self.selected_button_idx = 2
        self.content_scroll_offset = 0
        self.active_pane = "content"
        self.status_message = f"Editando tema '{slug}': ajusta valores y pulsa 'Guardar'."

    def _prompt_delete_theme(self, theme_name: str) -> None:
        """Solicita confirmación para borrar un tema de usuario en ~/.config/omarchy/themes."""
        slug = self.theme_engine.normalize_theme_slug(theme_name)
        user_slugs = {self.theme_engine.normalize_theme_slug(u) for u in self.theme_engine.list_user_themes()}
        if slug not in user_slugs:
            self.status_message = f"'{theme_name}' es un tema del sistema; solo se borran temas de usuario."
            return
        self._pending_delete_theme_slug = slug
        self.modal_state = "confirm_delete_theme"
        self.modal_selected_idx = 1

    def _execute_modal_choice(self, choice_idx: int) -> None:
        """Ejecuta la acción seleccionada dentro de la ventana modal activa."""
        if getattr(self, "modal_kb_recording", False):
            self._stop_keybind_recording()
        state = self.modal_state
        self.modal_state = None
        self.hover_modal_btn_idx = None
        self.hover_autostart_app_idx = None
        self.autostart_dropdown_open = False

        if state == "confirm_section_change":
            if choice_idx == 0:  # Descartar cambios y cambiar de sección
                self.settings = dict(self.saved_settings)
                self.autostart_items = [dict(x) for x in self.saved_autostart]
                self.keybind_items = [dict(x) for x in self.saved_keybinds]
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

        elif state == "confirm_delete_theme":
            t_slug = getattr(self, "_pending_delete_theme_slug", "")
            if choice_idx == 1 and t_slug:
                ok, msg = self.theme_engine.delete_user_theme(t_slug)
                self.available_themes = self.theme_engine.list_available_themes()
                self._sync_theme_into_settings()
                self.saved_settings = dict(self.settings)
                self.section_items = self._init_section_items()
                self.selected_item_idx = max(0, min(self.selected_item_idx, len(self.section_items["themes"]) - 1))
                self.status_message = msg
            else:
                self.status_message = "Borrado de tema cancelado."

        elif state == "edit_keybind":
            if 0 <= self.modal_kb_idx < len(self.keybind_items):
                entry = self.keybind_items[self.modal_kb_idx]
                if choice_idx == 1:
                    new_k = self._normalize_keybind_string(self.modal_kb_keys)
                    new_a = self.modal_kb_action.strip()
                    if new_k:
                        entry["keys"] = new_k
                    if new_a:
                        entry["cmd"] = new_a
                    self._sync_keybinds_into_settings()
                    self.config_sync.save_keybinds(self.keybind_items)
                    self.saved_keybinds = [dict(x) for x in self.keybind_items]
                    self.section_items["keybinds"] = self._build_keybinds_section_items()
                    self.status_message = f"✓ Atajo '{entry.get('title')}' guardado: {new_k}"
                elif choice_idx == 2:
                    cur_en = bool(entry.get("enabled", True))
                    entry["enabled"] = not cur_en
                    self._sync_keybinds_into_settings()
                    self.config_sync.save_keybinds(self.keybind_items)
                    self.saved_keybinds = [dict(x) for x in self.keybind_items]
                    self.section_items["keybinds"] = self._build_keybinds_section_items()
                    self.status_message = f"✓ Atajo '{entry.get('title')}' {'activado' if not cur_en else 'desactivado'}."
                else:
                    self.status_message = "Edicion de atajo cancelada."

        elif state == "add_keybind":
            if choice_idx == 1:
                new_k = self._normalize_keybind_string(self.modal_kb_keys)
                if getattr(self, "modal_kb_tab", "program") == "program":
                    base_cmd = self.modal_kb_app_selected_cmd.strip()
                    if not base_cmd:
                        filtered = self._get_filtered_kb_apps()
                        if filtered and 0 <= self.modal_kb_app_idx < len(filtered):
                            base_cmd = filtered[self.modal_kb_app_idx]["cmd"].strip()
                            if not self.modal_kb_app_selected_name:
                                self.modal_kb_app_selected_name = filtered[self.modal_kb_app_idx]["name"].strip()
                    extra_cmd = self.modal_kb_app_extra.strip()
                    if base_cmd and extra_cmd:
                        new_a = f"{base_cmd} {extra_cmd}"
                    else:
                        new_a = base_cmd
                    new_d = self.modal_kb_desc.strip() or self.modal_kb_app_selected_name.strip() or new_a
                else:
                    new_a = self.modal_kb_action.strip()
                    new_d = self.modal_kb_desc.strip() or new_a

                if new_k and new_a:
                    self.keybind_items.append({
                        "id": f"custom_{len(self.keybind_items)}",
                        "category": "ATAJOS PERSONALIZADOS",
                        "title": new_d,
                        "keys": new_k,
                        "default_keys": new_k,
                        "orig_lua_key": new_k,
                        "default_lua_expr": new_a,
                        "cmd": new_a,
                        "default_cmd": new_a,
                        "enabled": True,
                        "is_custom": True,
                    })
                    self._sync_keybinds_into_settings()
                    self.config_sync.save_keybinds(self.keybind_items)
                    self.saved_keybinds = [dict(x) for x in self.keybind_items]
                    self.section_items["keybinds"] = self._build_keybinds_section_items()
                    self.status_message = f"✓ Atajo '{new_d}' guardado: {new_k}"
                else:
                    self.status_message = "Atajo incompleto cancelado."
            else:
                self.status_message = "Nuevo atajo cancelado."

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
                    self.section_items["autostart"] = self._build_autostart_section_items()
                    self.status_message = f"Agregado en cola: {chosen_name} (Pulsa 'Aplicar' para guardar)"
                else:
                    self.status_message = "Entrada vacia cancelada."
            else:
                self.status_message = "Agregar a autostart cancelado."
            self.modal_input_text = ""
            self.autostart_selected_app_name = ""

        elif state == "input_theme_hex":
            if choice_idx == 1:
                hex_val = self.modal_input_text.strip()
                if not hex_val.startswith("#"):
                    hex_val = "#" + hex_val
                if re.match(r"^#[0-9A-Fa-f]{6}$", hex_val):
                    self._set_item_value(self.modal_hex_target, hex_val)
                    self.status_message = f"✓ Color actualizado a {hex_val}."
                else:
                    self.status_message = "Formato Hex invalido (usa #RRGGBB, ej. #E31B23)."
            self.modal_input_text = ""

        elif state == "input_creator_text":
            if choice_idx == 1:
                txt_val = self.modal_input_text.strip()
                if txt_val:
                    if self.modal_text_target.startswith("creator:"):
                        field = self.modal_text_target.replace("creator:", "")
                        self.theme_creator_spec[field] = txt_val
                        self.status_message = f"✓ Valor '{field}' establecido en: {txt_val}"
                    else:
                        self._set_item_value(self.modal_text_target, txt_val)
                        self.status_message = f"✓ Valor establecido en: {txt_val}"
            self.modal_input_text = ""

    # ==========================
    # MANEJO DE ENTRADA Y RATÓN
    # ==========================

    def _move_content_selection(self, delta: int) -> None:
        """Mueve la selección vertical en el panel derecho saltando encabezados ('header')."""
        active_sections = self._get_active_sections()
        sec_id = active_sections[self.current_section_idx][1]
        items = self.section_items.get(sec_id, [])
        if not items:
            return
        idx = self.selected_item_idx + delta
        max_steps = len(items) + 1
        steps = 0
        while 0 <= idx < len(items) and items[idx].item_type == "header" and steps < max_steps:
            idx += (1 if delta >= 0 else -1)
            steps += 1
        if idx < 0:
            self.selected_item_idx = 0
        elif idx >= len(items):
            self.active_pane = "buttons"
            self.selected_button_idx = 2
        else:
            self.selected_item_idx = idx

    def handle_input(self, fd: Any) -> None:
        if isinstance(fd, (bytes, bytearray)):
            ch = bytes(fd)
        else:
            if getattr(self, "modal_kb_recording", False):
                if self._check_hyprland_keybind_recording():
                    try:
                        import termios
                        termios.tcflush(fd, termios.TCIFLUSH)
                    except Exception:
                        pass
                    return
            if self._check_compose_recording():
                return

            r, _, _ = select.select([fd], [], [], 0.04)
            if not r:
                if getattr(self, "modal_kb_recording", False):
                    if self._check_hyprland_keybind_recording():
                        try:
                            import termios
                            termios.tcflush(fd, termios.TCIFLUSH)
                        except Exception:
                            pass
                        return
                if self._check_compose_recording():
                    return
                return

            # Descartar rafagas de caracteres residuales posteriores a la finalizacion de una captura
            if time.time() - getattr(self, "_last_recording_finish_time", 0.0) < 0.25:
                try:
                    os.read(fd, 4096)
                    import termios
                    termios.tcflush(fd, termios.TCIFLUSH)
                except Exception:
                    pass
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
        self.hover_context_idx = None

        # 0a. Si la ventana modal de tecla Compose está activa
        if self.modal_state == "record_compose":
            if self._check_compose_recording():
                return
            if ch in (b"\x1b", b"\x7f", b"\x08"):
                self._apply_compose_choice("none", "Desactivada (Recomendado)")
                return
            return

        # 0. Si el menú contextual de clic secundario está abierto
        if self.context_menu_open and not self.modal_state:
            if ch in (b"\x1b", b"q", b"Q") and len(ch) == 1:
                self.context_menu_open = False
                return
            if ch in (b"\x1b[A", b"k", b"K"):  # Arriba / k
                self.context_menu_idx = max(0, self.context_menu_idx - 1)
                return
            if ch in (b"\x1b[B", b"j", b"J"):  # Abajo / j
                self.context_menu_idx = min(len(self.context_menu_items) - 1, self.context_menu_idx + 1)
                return
            if ch in (b"\r", b"\n", b" "):
                if 0 <= self.context_menu_idx < len(self.context_menu_items):
                    act_id = self.context_menu_items[self.context_menu_idx][0]
                    self._execute_context_action(act_id)
                else:
                    self.context_menu_open = False
                return
            self.context_menu_open = False
            return

        # 0.5 Si el buscador global está abierto
        if getattr(self, "search_open", False) and not self.modal_state:
            if ch in (b"\x1b",):
                self.search_open = False
                self.search_query = ""
                self.status_message = "Buscador cerrado."
                return
            if ch in (b"\x1b[A", b"k", b"K"):  # Arriba / k
                self.search_selected_idx = max(0, self.search_selected_idx - 1)
                return
            if ch in (b"\x1b[B", b"j", b"J"):  # Abajo / j
                if self.search_results:
                    self.search_selected_idx = min(len(self.search_results) - 1, self.search_selected_idx + 1)
                return
            if ch == b"\x1b[5~":  # Page Up
                self.search_selected_idx = max(0, self.search_selected_idx - 5)
                return
            if ch == b"\x1b[6~" and self.search_results:  # Page Down
                self.search_selected_idx = min(len(self.search_results) - 1, self.search_selected_idx + 5)
                return
            if ch in (b"\x1b[H", b"\x1b[1~"):  # Home
                self.search_selected_idx = 0
                return
            if ch in (b"\x1b[F", b"\x1b[4~") and self.search_results:  # End
                self.search_selected_idx = max(0, len(self.search_results) - 1)
                return
            if ch in (b"\r", b"\n"):
                self._navigate_to_search_result(exec_action=False)
                return
            if ch in (b" ", b"\t"):
                self._navigate_to_search_result(exec_action=True)
                return
            if ch in (b"\x7f", b"\x08"):  # Backspace
                self.search_query = self.search_query[:-1]
                self._perform_global_search()
                return
            try:
                decoded = ch.decode("utf-8", errors="ignore")
                for c in decoded:
                    if c.isprintable() and c not in ("\r", "\n", "\t"):
                        self.search_query += c
                self._perform_global_search()
            except Exception:
                pass
            return

        # 1. Si hay un menú desplegable (dropdown) abierto en el panel principal
        if self.dropdown_open and not self.modal_state:
            if ch in (b"\x1b", b"q", b"Q") and len(ch) == 1:
                self.dropdown_open = False
                return
            if ch in (b"\x1b[A", b"k", b"K"):  # Arriba / k
                self.dropdown_idx = max(0, self.dropdown_idx - 1)
                return
            if ch in (b"\x1b[B", b"j", b"J"):  # Abajo / j
                self.dropdown_idx = min(len(self.dropdown_options) - 1, self.dropdown_idx + 1)
                return
            if ch in (b"\x1b[5~",):  # Page Up
                self.dropdown_idx = max(0, self.dropdown_idx - 5)
                return
            if ch in (b"\x1b[6~",):  # Page Down
                self.dropdown_idx = min(len(self.dropdown_options) - 1, self.dropdown_idx + 5)
                return
            if ch in (b"\x1b[H", b"\x1b[1~"):  # Home
                self.dropdown_idx = 0
                return
            if ch in (b"\x1b[F", b"\x1b[4~"):  # End
                self.dropdown_idx = max(0, len(self.dropdown_options) - 1)
                return
            if ch in (b"\r", b"\n", b" "):
                if self.dropdown_item and 0 <= self.dropdown_idx < len(self.dropdown_options):
                    chosen = self.dropdown_options[self.dropdown_idx]
                    target_key = self.dropdown_item.key
                    self.dropdown_open = False
                    if chosen == "Escribir #Hex...":
                        self.modal_state = "input_theme_hex"
                        self.modal_hex_target = target_key
                        self.modal_input_text = str(self._get_item_value(self.dropdown_item))
                        self.modal_selected_idx = 1
                        return
                    elif chosen in ("Escribir ruta...", "Escribir distribucion..."):
                        self.modal_state = "input_creator_text"
                        self.modal_text_target = target_key
                        self.modal_input_text = str(self._get_item_value(self.dropdown_item))
                        self.modal_selected_idx = 1
                        return
                    else:
                        self._set_item_value(target_key, chosen)
                self.dropdown_open = False
                return
            try:
                char = ch.decode("utf-8", errors="ignore").lower()
                if len(char) == 1 and char.isalnum():
                    for o_idx, opt in enumerate(self.dropdown_options):
                        if opt.lower().startswith(char):
                            self.dropdown_idx = o_idx
                            break
                    return
            except Exception:
                pass
            return

        # 1b. Si el modal de edición/creación de atajos está activo
        if self.modal_state in ("edit_keybind", "add_keybind"):
            max_field = self._get_keybind_max_field()
            btn_field = max_field + 1
            max_btn = 1 if self.modal_state == "add_keybind" else 2

            # Modo de captura interactiva activa (escuchando combinación directa en tiempo real)
            if getattr(self, "modal_kb_recording", False):
                if self._check_hyprland_keybind_recording():
                    try:
                        import termios
                        termios.tcflush(fd, termios.TCIFLUSH)
                    except Exception:
                        pass
                    return
                if ch == b"\x1b" and len(ch) == 1:
                    self._stop_keybind_recording()
                    self.status_message = "Captura de atajo cancelada."
                    return
                if not getattr(self, "_hypr_rec_active", False) and not os.path.exists(self._rec_file):
                    self._handle_keybind_recording_input(ch)
                return

            if ch == b"\x1b" and len(ch) == 1:
                if self.modal_state == "add_keybind" and getattr(self, "modal_kb_tab", "program") == "program" and self.modal_kb_app_dropdown_open:
                    self.modal_kb_app_dropdown_open = False
                    return
                self.modal_state = None
                return

            # Atajos directos para alternar pestañas superiores en modo creación
            if self.modal_state == "add_keybind":
                if ch in (b"\x1bOP", b"\x1b[11~", b"\x1b[[A", b"\x1b1"):  # F1 o Alt+1 -> Programa
                    self.modal_kb_tab = "program"
                    self.modal_kb_app_dropdown_open = False
                    if self.modal_kb_field > 3:
                        self.modal_kb_field = 0
                    return
                if ch in (b"\x1bOQ", b"\x1b[12~", b"\x1b[[B", b"\x1b2"):  # F2 o Alt+2 -> Comando
                    self.modal_kb_tab = "command"
                    self.modal_kb_app_dropdown_open = False
                    if self.modal_kb_field > 2:
                        self.modal_kb_field = 0
                    return

            # Si el foco está en la barra de pestañas (-1)
            if self.modal_state == "add_keybind" and self.modal_kb_field == -1:
                if ch in (b"\x1b[D", b"h", b"H", b"\x1b[C", b"l", b"L"):
                    self.modal_kb_tab = "command" if self.modal_kb_tab == "program" else "program"
                    self.modal_kb_app_dropdown_open = False
                    return
                if ch in (b"\t", b"\x1b[B", b"\r", b"\n"):
                    self.modal_kb_field = 0
                    return
                if ch in (b"\x1b[A", b"\x1b[Z"):
                    self.modal_kb_field = btn_field
                    return

            if self.modal_kb_field == 0 and ch in (b"1", b"2", b"3", b"4"):
                mod_map = {b"1": "SUPER", b"2": "CTRL", b"3": "ALT", b"4": "SHIFT"}
                self._toggle_kb_modifier(mod_map[ch])
                return

            # Interacción con la lista desplegable de programas (Campo 1 en modo 'program')
            if self.modal_state == "add_keybind" and getattr(self, "modal_kb_tab", "program") == "program" and self.modal_kb_field == 1:
                filtered_kb = self._get_filtered_kb_apps()
                if self.modal_kb_app_dropdown_open:
                    if ch in (b"\x1b[A", b"k", b"K"):
                        self.modal_kb_app_idx = max(0, self.modal_kb_app_idx - 1)
                        return
                    if ch in (b"\x1b[B", b"j", b"J"):
                        if filtered_kb:
                            self.modal_kb_app_idx = min(len(filtered_kb) - 1, self.modal_kb_app_idx + 1)
                        return
                    if ch == b"\x1b[5~":
                        self.modal_kb_app_idx = max(0, self.modal_kb_app_idx - 5)
                        return
                    if ch == b"\x1b[6~" and filtered_kb:
                        self.modal_kb_app_idx = min(len(filtered_kb) - 1, self.modal_kb_app_idx + 5)
                        return
                    if ch in (b"\r", b"\n"):
                        self._select_kb_dropdown_app(self.modal_kb_app_idx)
                        return
                    if ch == b"\t":
                        self.modal_kb_app_dropdown_open = False
                        self.modal_kb_field = 2
                        return
                else:
                    if ch in (b"\r", b"\n", b" ", b"\x1b[B"):
                        self.modal_kb_app_dropdown_open = True
                        return

            if ch in (b"\t", b"\x1b[B"):  # Tab o Flecha Abajo avanza campos
                if self.modal_kb_field == btn_field:
                    self.modal_kb_field = -1 if self.modal_state == "add_keybind" else 0
                else:
                    self.modal_kb_field += 1
                return
            if ch in (b"\x1b[A", b"\x1b[Z"):  # Flecha Arriba o Shift+Tab retrocede
                if self.modal_kb_field == -1:
                    self.modal_kb_field = btn_field
                elif self.modal_kb_field == 0:
                    self.modal_kb_field = -1 if self.modal_state == "add_keybind" else btn_field
                else:
                    self.modal_kb_field -= 1
                return
            if ch in (b"\x1b[D", b"h", b"H"):  # Flecha Izquierda / h
                self.modal_selected_idx = max(0, self.modal_selected_idx - 1)
                return
            if ch in (b"\x1b[C", b"l", b"L"):  # Flecha Derecha / l
                self.modal_selected_idx = min(max_btn, self.modal_selected_idx + 1)
                return
            if ch in (b"\r", b"\n"):
                if self.modal_kb_field == 0:
                    self._start_keybind_recording()
                    return
                elif self.modal_kb_field == btn_field:
                    self._execute_modal_choice(self.modal_selected_idx)
                    return
                elif self.modal_kb_field < max_field:
                    self.modal_kb_field += 1
                    return
                else:
                    self._execute_modal_choice(1)
                    return
            if ch == b" ":
                if self.modal_kb_field == 0:
                    self._start_keybind_recording()
                    return
                elif self.modal_kb_field == btn_field:
                    self._execute_modal_choice(self.modal_selected_idx)
                    return
            if ch in (b"\x7f", b"\x08"):
                if self.modal_kb_field == 0:
                    s = self.modal_kb_keys.rstrip()
                    if " + " in s:
                        self.modal_kb_keys = s.rsplit(" + ", 1)[0]
                    else:
                        self.modal_kb_keys = self.modal_kb_keys[:-1]
                elif self.modal_kb_field == 1:
                    if self.modal_state == "add_keybind" and getattr(self, "modal_kb_tab", "program") == "program":
                        self.modal_kb_app_search = self.modal_kb_app_search[:-1]
                        self.modal_kb_app_idx = 0
                        self.modal_kb_app_scroll = 0
                    else:
                        self.modal_kb_action = self.modal_kb_action[:-1]
                elif self.modal_kb_field == 2:
                    if self.modal_state == "add_keybind" and getattr(self, "modal_kb_tab", "program") == "program":
                        self.modal_kb_app_extra = self.modal_kb_app_extra[:-1]
                    else:
                        self.modal_kb_desc = self.modal_kb_desc[:-1]
                elif self.modal_kb_field == 3:
                    self.modal_kb_desc = self.modal_kb_desc[:-1]
                return
            try:
                decoded = ch.decode("utf-8", errors="ignore")
                for c in decoded:
                    if c.isprintable() and c not in ("\r", "\n", "\t"):
                        if self.modal_kb_field == 0:
                            all_mods = ["SUPER", "CTRL", "ALT", "SHIFT"]
                            clean_text = self.modal_kb_keys.replace("...", "").strip()
                            if clean_text.endswith("+"):
                                clean_text = clean_text[:-1].strip()
                            norm = self._normalize_keybind_string(clean_text)
                            parts = [p.strip().upper() for p in norm.split("+") if p.strip()]
                            has_only_mods = parts and all(p in all_mods for p in parts)
                            if has_only_mods and c.isalnum():
                                self.modal_kb_keys = " + ".join(parts + [c.upper()])
                            elif c in ("+", " ", ","):
                                self.modal_kb_keys = (clean_text + " ") if clean_text else ""
                            else:
                                self.modal_kb_keys = (clean_text + " " if clean_text and not clean_text.endswith(" ") else clean_text) + c
                        elif self.modal_kb_field == 1:
                            if self.modal_state == "add_keybind" and getattr(self, "modal_kb_tab", "program") == "program":
                                self.modal_kb_app_search += c
                                self.modal_kb_app_dropdown_open = True
                                self.modal_kb_app_idx = 0
                                self.modal_kb_app_scroll = 0
                            else:
                                self.modal_kb_action += c
                        elif self.modal_kb_field == 2:
                            if self.modal_state == "add_keybind" and getattr(self, "modal_kb_tab", "program") == "program":
                                self.modal_kb_app_extra += c
                            else:
                                self.modal_kb_desc += c
                        elif self.modal_kb_field == 3:
                            self.modal_kb_desc += c
            except Exception:
                pass
            return

        # 2. Si hay una ventana modal interactiva activa (input_autostart, input_theme_hex o input_creator_text)
        if self.modal_state in ("input_autostart", "input_theme_hex", "input_creator_text"):
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
                    if ch in (b"\x1b[A", b"k", b"K") and self.autostart_dropdown_open:  # Flecha Arriba / k
                        self.autostart_app_idx = max(0, self.autostart_app_idx - 1)
                        return
                    if ch in (b"\x1b[B", b"j", b"J"):  # Flecha Abajo / j abre o navega el selector desplegable
                        if not self.autostart_dropdown_open:
                            self.autostart_dropdown_open = True
                        elif filtered:
                            self.autostart_app_idx = min(len(filtered) - 1, self.autostart_app_idx + 1)
                        return
                    if ch in (b"\x1b[5~",) and self.autostart_dropdown_open:  # Page Up
                        self.autostart_app_idx = max(0, self.autostart_app_idx - 5)
                        return
                    if ch in (b"\x1b[6~",) and self.autostart_dropdown_open and filtered:  # Page Down
                        self.autostart_app_idx = min(len(filtered) - 1, self.autostart_app_idx + 5)
                        return
                    if ch in (b"\r", b"\n") and self.autostart_dropdown_open:
                        self._select_autostart_dropdown_app(self.autostart_app_idx)
                        return

            if ch in (b"\x1b[D", b"\x1b[Z", b"h", b"H"):
                self.modal_selected_idx = max(0, self.modal_selected_idx - 1)
                return
            if ch in (b"\x1b[C", b"l", b"L"):
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
            if ch in (b"\x1b[D", b"\x1b[Z", b"h", b"H"):  # Izquierda / Shift+Tab / h
                self.modal_selected_idx = max(0, self.modal_selected_idx - 1)
                return
            if ch in (b"\x1b[C", b"\t", b"l", b"L"):  # Derecha / Tab / l
                self.modal_selected_idx = min(max_idx, self.modal_selected_idx + 1)
                return
            if ch in (b"\r", b"\n", b" "):
                self._execute_modal_choice(self.modal_selected_idx)
                return
            return

        # Salir o regresar con Esc / q
        if ch == b"\x1b" and len(ch) == 1:
            if self.view_mode == "theme_creator":
                self.view_mode = "main"
                self.creator_is_editing = False
                self.creator_editing_slug = ""
                self.current_section_idx = self._prev_main_section_idx
                self.selected_item_idx = 0
                self.content_scroll_offset = 0
                self.status_message = "Edicion de tema cancelada."
                return
            if self.active_pane != "sidebar":
                self.active_pane = "sidebar"
                self.status_message = "Foco en el panel izquierdo (Barra lateral)."
                return
            self.running = False
            return

        if ch in (b"q", b"Q") and len(ch) == 1:
            self.running = False
            return

        # Atajo dedicado para volver al panel izquierdo (barra lateral):
        # 'b', 'B', Backspace (\x7f, \x08), Ctrl+Left (\x1b[1;5D), Alt+Left (\x1b[1;3D)
        if ch in (b"b", b"B", b"\x7f", b"\x08", b"\x1b[1;5D", b"\x1b[1;3D"):
            self.active_pane = "sidebar"
            self.status_message = "Foco en el panel izquierdo (Barra lateral)."
            return

        # Eliminar entrada de autostart, atajo o tema personalizado con Supr / Delete (\x1b[3~) o 'x'
        if ch in (b"\x1b[3~", b"x", b"X") and self.view_mode == "main":
            active_sections = self._get_active_sections()
            sec_id = active_sections[self.current_section_idx][1]
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
                        self._prompt_delete_theme(t_slug)
            elif sec_id == "keybinds":
                items = self.section_items.get("keybinds", [])
                if 0 <= self.selected_item_idx < len(items):
                    cur_item = items[self.selected_item_idx]
                    if cur_item.key.startswith("keybind:item:"):
                        kb_idx = int(cur_item.key.split(":")[-1])
                        if 0 <= kb_idx < len(self.keybind_items):
                            entry = self.keybind_items[kb_idx]
                            if entry.get("is_custom"):
                                removed = self.keybind_items.pop(kb_idx)
                                self._sync_keybinds_into_settings()
                                self.section_items["keybinds"] = self._build_keybinds_section_items()
                                self.status_message = f"Atajo '{removed.get('title')}' eliminado."
                            else:
                                entry["enabled"] = not bool(entry.get("enabled", True))
                                self._sync_keybinds_into_settings()
                                self.section_items["keybinds"] = self._build_keybinds_section_items()
                                st = "activado" if entry["enabled"] else "desactivado"
                                self.status_message = f"Atajo '{entry.get('title')}' {st} (Pulsa 'Aplicar')."
            return

        # Menú contextual con tecla m / M o tecla Menú
        if ch in (b"m", b"M", b"\x1b[29~") and not self.modal_state and not self.dropdown_open:
            self._open_context_menu_for_current_selection()
            return
            
        # Atajo para buscador global (tecla /)
        if ch == b"/" and not self.modal_state and not getattr(self, "search_open", False) and not self.dropdown_open and not self.context_menu_open:
            self._open_search()
            return

        # Atajos rápidos físicos directos (a/s/g: Aplicar/Guardar, c: Cancelar, r: Restablecer)
        if ch in (b"a", b"A", b"s", b"S", b"g", b"G"):
            self.save_all()
            return
        if ch in (b"c", b"C"):
            self.cancel_changes()
            return
        if ch in (b"r", b"R") and self.view_mode != "theme_creator":
            self.reset_to_defaults()
            return

        # Atajos numéricos 1-9 directos en la barra lateral
        if self.active_pane == "sidebar" and ch in (b"1", b"2", b"3", b"4", b"5", b"6", b"7", b"8", b"9"):
            target_s = int(ch) - 1
            active_sections = self._get_active_sections()
            if 0 <= target_s < len(active_sections):
                self._request_section_change(target_s, focus_content=False)
            return

        # Cambiar foco con Tab (avance) y Shift+Tab (retroceso)
        if ch == b"\t":
            if self.active_pane == "sidebar":
                self.active_pane = "content"
            elif self.active_pane == "content":
                self.active_pane = "buttons"
                if self.view_mode == "theme_creator" and self.selected_button_idx == 0:
                    self.selected_button_idx = 2
            else:
                self.active_pane = "sidebar"
            return

        if ch == b"\x1b[Z":  # Shift+Tab: ciclo inverso
            if self.active_pane == "sidebar":
                self.active_pane = "buttons"
                if self.view_mode == "theme_creator" and self.selected_button_idx == 0:
                    self.selected_button_idx = 2
            elif self.active_pane == "buttons":
                self.active_pane = "content"
            else:
                self.active_pane = "sidebar"
            return

        # Page Up (\x1b[5~) y Page Down (\x1b[6~)
        if ch == b"\x1b[5~":  # Page Up
            if self.active_pane == "sidebar":
                self._request_section_change(max(0, self.current_section_idx - 5), focus_content=False)
            elif self.active_pane == "content":
                self._move_content_selection(-5)
            return

        if ch == b"\x1b[6~":  # Page Down
            if self.active_pane == "sidebar":
                active_sections = self._get_active_sections()
                self._request_section_change(min(len(active_sections) - 1, self.current_section_idx + 5), focus_content=False)
            elif self.active_pane == "content":
                self._move_content_selection(5)
            return

        # Home (\x1b[H / \x1b[1~) y End (\x1b[F / \x1b[4~)
        if ch in (b"\x1b[H", b"\x1b[1~"):
            if self.active_pane == "sidebar":
                self._request_section_change(0, focus_content=False)
            elif self.active_pane == "content":
                self.selected_item_idx = 0
            return

        if ch in (b"\x1b[F", b"\x1b[4~"):
            if self.active_pane == "sidebar":
                active_sections = self._get_active_sections()
                self._request_section_change(len(active_sections) - 1, focus_content=False)
            elif self.active_pane == "content":
                active_sections = self._get_active_sections()
                sec_id = active_sections[self.current_section_idx][1]
                items = self.section_items.get(sec_id, [])
                if items:
                    self.selected_item_idx = len(items) - 1
            return

        # Navegación izquierda (Flecha Izquierda / h)
        if ch in (b"\x1b[D", b"h"):
            if self.active_pane == "buttons":
                min_btn = 1 if self.view_mode == "theme_creator" else 0
                if ch == b"h" or self.selected_button_idx == min_btn:
                    self.active_pane = "sidebar"
                else:
                    self.selected_button_idx = max(min_btn, self.selected_button_idx - 1)
            elif self.active_pane == "content":
                if ch == b"h":
                    self.active_pane = "sidebar"
                else:
                    active_sections = self._get_active_sections()
                    sec_id = active_sections[self.current_section_idx][1]
                    items = self.section_items.get(sec_id, [])
                    if items and 0 <= self.selected_item_idx < len(items):
                        item = items[self.selected_item_idx]
                        if item.item_type in ("stepper", "slider", "select"):
                            self._adjust_current_item(delta=-1)
                        else:
                            self.active_pane = "sidebar"
                    else:
                        self.active_pane = "sidebar"
            else:
                self.active_pane = "sidebar"
            return

        # Navegación derecha (Flecha Derecha / l)
        if ch in (b"\x1b[C", b"l"):
            if self.active_pane == "buttons":
                self.selected_button_idx = min(2, self.selected_button_idx + 1)
            elif self.active_pane == "content":
                self._adjust_current_item(delta=1)
            else:
                self.active_pane = "content"
            return

        # Ajuste de valores con + / - / [ / ]
        if ch in (b"+", b"="):
            if self.active_pane == "content":
                self._adjust_current_item(delta=1)
            return

        if ch in (b"-", b"_"):
            if self.active_pane == "content":
                self._adjust_current_item(delta=-1)
            return

        # Navegación vertical arriba (Flecha Arriba / k)
        if ch in (b"\x1b[A", b"k"):
            if self.active_pane == "buttons":
                self.active_pane = "content"
            elif self.active_pane == "sidebar":
                self._request_section_change(self.current_section_idx - 1, focus_content=False)
            else:
                self._move_content_selection(-1)
            return

        # Navegación vertical abajo (Flecha Abajo / j)
        if ch in (b"\x1b[B", b"j"):
            if self.active_pane == "sidebar":
                self._request_section_change(self.current_section_idx + 1, focus_content=False)
            elif self.active_pane == "content":
                self._move_content_selection(1)
            return

        # Espacio para conmutar directamente (toggle / activar atajo / abrir dropdown)
        if ch == b" ":
            if self.active_pane == "sidebar":
                self.active_pane = "content"
            elif self.active_pane == "buttons":
                if self.selected_button_idx == 0 and self.view_mode != "theme_creator":
                    self.reset_to_defaults()
                elif self.selected_button_idx == 1:
                    self.cancel_changes()
                elif self.selected_button_idx == 2:
                    self.save_all()
            else:
                # Conmutar atajo o autostart directamente sin necesidad de abrir modal
                active_sections = self._get_active_sections()
                sec_id = active_sections[self.current_section_idx][1]
                items = self.section_items.get(sec_id, [])
                if items and 0 <= self.selected_item_idx < len(items):
                    item = items[self.selected_item_idx]
                    if item.key.startswith("keybind:item:"):
                        kb_idx = int(item.key.split(":")[-1])
                        if 0 <= kb_idx < len(self.keybind_items):
                            entry = self.keybind_items[kb_idx]
                            cur_en = bool(entry.get("enabled", True))
                            entry["enabled"] = not cur_en
                            self._sync_keybinds_into_settings()
                            self.config_sync.save_keybinds(self.keybind_items)
                            self.saved_keybinds = [dict(x) for x in self.keybind_items]
                            self.section_items["keybinds"] = self._build_keybinds_section_items()
                            st = "activado" if entry["enabled"] else "desactivado"
                            self.status_message = f"✓ Atajo '{entry.get('title')}' {st}."
                            return
                    elif item.key.startswith("autostart:item:"):
                        as_idx = int(item.key.split(":")[-1])
                        if 0 <= as_idx < len(self.autostart_items):
                            cur_en = bool(self.autostart_items[as_idx].get("enabled", True))
                            self.autostart_items[as_idx]["enabled"] = not cur_en
                            self._sync_autostart_into_settings()
                            self.section_items["autostart"] = self._build_autostart_section_items()
                            st = "activada" if not cur_en else "desactivada"
                            self.status_message = f"Entrada autostart {st} (Pulsa Aplicar)."
                            return
                self._activate_current_item()
            return

        # Enter para activar/abrir/confirmar
        if ch in (b"\r", b"\n"):
            if self.active_pane == "sidebar":
                self.active_pane = "content"
            elif self.active_pane == "buttons":
                if self.selected_button_idx == 0 and self.view_mode != "theme_creator":
                    self.reset_to_defaults()
                elif self.selected_button_idx == 1:
                    self.cancel_changes()
                elif self.selected_button_idx == 2:
                    self.save_all()
            else:
                self._activate_current_item()
            return

    def _cycle_input_modal_kind(self) -> None:
        """Alterna el selector de tipo en el modal de autostart."""
        if self.modal_state == "input_autostart":
            self.modal_input_kind = "exec" if self.modal_input_kind == "launch" else "launch"
            if self.modal_input_kind == "exec":
                self.autostart_dropdown_open = False
                self.autostart_selected_app_name = ""

    def _handle_mouse_event(self, btn: int, x: int, y: int, act: bytes) -> None:
        """Procesa clics, clic secundario (btn == 2), arrastres, rueda del ratón y movimiento hover (btn == 35)."""
        cols, rows = shutil.get_terminal_size((84, 42))
        sidebar_w = self._get_sidebar_width(cols)
        active_sections = self._get_active_sections()
        
        # -1. Si el buscador global está abierto
        if getattr(self, "search_open", False) and not self.modal_state:
            sy1, sy2, sx1, sx2 = self._search_box_bounds
            if act == b"M" and btn == 35:
                if sy1 <= y <= sy2 and sx1 <= x <= sx2 and y in self._search_click_map:
                    self.hover_search_idx = self._search_click_map[y]
                    self.search_selected_idx = self.hover_search_idx
                else:
                    self.hover_search_idx = None
                return
            if act == b"M" and btn in (64, 65):
                if btn == 64:
                    self.search_selected_idx = max(0, self.search_selected_idx - 1)
                else:
                    if self.search_results:
                        self.search_selected_idx = min(len(self.search_results) - 1, self.search_selected_idx + 1)
                return
            if act == b"M" and btn == 0:
                if sy1 <= y <= sy2 and sx1 <= x <= sx2:
                    if y in self._search_click_map:
                        self.search_selected_idx = self._search_click_map[y]
                        self._navigate_to_search_result(exec_action=False)
                    return
                else:
                    self.search_open = False
                return

        # 0. Si el menú contextual de clic secundario está abierto
        if self.context_menu_open and not self.modal_state:
            cy1, cy2, cx1, cx2 = self._context_box_bounds
            if act == b"M" and btn == 35:
                if cy1 <= y <= cy2 and cx1 <= x <= cx2 and y in self._context_row_map:
                    self.hover_context_idx = self._context_row_map[y]
                    self.context_menu_idx = self.hover_context_idx
                else:
                    self.hover_context_idx = None
                return
            if act == b"M" and btn in (64, 65):
                if btn == 64:
                    self.context_menu_idx = max(0, self.context_menu_idx - 1)
                else:
                    self.context_menu_idx = min(len(self.context_menu_items) - 1, self.context_menu_idx + 1)
                return
            if act == b"M" and btn == 0:
                if cy1 <= y <= cy2 and cx1 <= x <= cx2 and y in self._context_row_map:
                    c_idx = self._context_row_map[y]
                    if 0 <= c_idx < len(self.context_menu_items):
                        self._execute_context_action(self.context_menu_items[c_idx][0])
                        return
                self.context_menu_open = False
                return
            if act == b"M" and btn == 2:
                self._open_context_menu(x, y, sidebar_w)
                return
            return

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
                        target_key = self.dropdown_item.key
                        self.dropdown_open = False
                        if chosen == "Escribir #Hex...":
                            self.modal_state = "input_theme_hex"
                            self.modal_hex_target = target_key
                            self.modal_input_text = str(self._get_item_value(self.dropdown_item))
                            self.modal_selected_idx = 1
                            return
                        elif chosen in ("Escribir ruta...", "Escribir distribucion..."):
                            self.modal_state = "input_creator_text"
                            self.modal_text_target = target_key
                            self.modal_input_text = str(self._get_item_value(self.dropdown_item))
                            self.modal_selected_idx = 1
                            return
                        else:
                            self._set_item_value(target_key, chosen)
                self.dropdown_open = False
                return
            if act == b"M" and btn == 2:
                self.dropdown_open = False
                self._open_context_menu(x, y, sidebar_w)
                return
            return

        # 2. Si hay una ventana modal abierta, dirigir clics, rueda y hover al modal
        if self.modal_state:
            if act == b"M" and btn == 35:
                m_ymin, m_ymax = self._modal_button_row_range
                self.hover_modal_btn_idx = None
                self.hover_autostart_app_idx = None
                if self.modal_state in ("edit_keybind", "add_keybind"):
                    self.hover_kb_mod = None
                    self.hover_kb_rec = False
                    self.hover_kb_tab = None
                    self.hover_kb_app_idx = None
                    if self.modal_state == "add_keybind":
                        for tab_name, (ty, tx1, tx2) in self._kb_tab_click_ranges.items():
                            if y == ty and tx1 <= x <= tx2:
                                self.hover_kb_tab = tab_name
                                return
                        if getattr(self, "modal_kb_tab", "program") == "program" and self.modal_kb_app_dropdown_open:
                            lx_min, lx_max = self._kb_app_list_x_range
                            if y in self._kb_app_list_click_map and lx_min <= x <= lx_max:
                                self.hover_kb_app_idx = self._kb_app_list_click_map[y]
                                return
                    for mod_name, (my, mx1, mx2) in self._kb_mod_chips.items():
                        if y == my and mx1 <= x <= mx2:
                            self.hover_kb_mod = mod_name
                            return
                    ry, rx1, rx2 = self._kb_rec_btn_range
                    if y == ry and rx1 <= x <= rx2:
                        self.hover_kb_rec = True
                        return
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

            if act == b"M" and btn in (64, 65):
                if self.modal_state == "add_keybind" and getattr(self, "modal_kb_tab", "program") == "program" and self.modal_kb_app_dropdown_open:
                    filtered = self._get_filtered_kb_apps()
                    if filtered:
                        if btn == 64:
                            self.modal_kb_app_idx = max(0, self.modal_kb_app_idx - 1)
                        else:
                            self.modal_kb_app_idx = min(len(filtered) - 1, self.modal_kb_app_idx + 1)
                    return
                if self.modal_state == "input_autostart" and self.modal_input_kind == "launch" and self.autostart_dropdown_open:
                    filtered = self._get_filtered_autostart_apps()
                    if filtered:
                        if btn == 64:
                            self.autostart_app_idx = max(0, self.autostart_app_idx - 1)
                        else:
                            self.autostart_app_idx = min(len(filtered) - 1, self.autostart_app_idx + 1)
                    return
                return

            if act == b"M" and btn == 0:
                if self.modal_state in ("edit_keybind", "add_keybind"):
                    if self.modal_state == "add_keybind":
                        for tab_name, (ty, tx1, tx2) in self._kb_tab_click_ranges.items():
                            if y == ty and tx1 <= x <= tx2:
                                self.modal_kb_tab = tab_name
                                self.modal_kb_app_dropdown_open = False
                                if self.modal_kb_field > self._get_keybind_max_field():
                                    self.modal_kb_field = 0
                                return
                        if getattr(self, "modal_kb_tab", "program") == "program":
                            ddy1, ddy2, ddx1, ddx2 = self._kb_app_dropdown_btn_range
                            if ddy1 <= y <= ddy2 and ddx1 <= x <= ddx2:
                                self.modal_kb_app_dropdown_open = not self.modal_kb_app_dropdown_open
                                self.modal_kb_field = 1
                                return
                            if self.modal_kb_app_dropdown_open:
                                lx_min, lx_max = self._kb_app_list_x_range
                                if y in self._kb_app_list_click_map and lx_min <= x <= lx_max:
                                    clicked_idx = self._kb_app_list_click_map[y]
                                    self._select_kb_dropdown_app(clicked_idx)
                                    return
                    for mod_name, (my, mx1, mx2) in self._kb_mod_chips.items():
                        if y == my and mx1 <= x <= mx2:
                            self._toggle_kb_modifier(mod_name)
                            return
                    ry, rx1, rx2 = self._kb_rec_btn_range
                    if y == ry and rx1 <= x <= rx2:
                        self.modal_kb_field = 0
                        if getattr(self, "modal_kb_recording", False):
                            self._stop_keybind_recording()
                        else:
                            self._start_keybind_recording()
                        return
                    for f_idx, (fy1, fy2, fx1, fx2) in self._kb_field_click_ranges.items():
                        if fy1 <= y <= fy2 and fx1 <= x <= fx2:
                            self.modal_kb_field = f_idx
                            if f_idx != 1:
                                self.modal_kb_app_dropdown_open = False
                            if f_idx == 0:
                                if getattr(self, "modal_kb_recording", False):
                                    self._stop_keybind_recording()
                                else:
                                    self._start_keybind_recording()
                            elif getattr(self, "modal_kb_recording", False):
                                self._stop_keybind_recording()
                            return
                ky, kxmin, kxmax = self._modal_kind_click_range
                if y == ky and kxmin <= x <= kxmax:
                    self._cycle_input_modal_kind()
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
            # 0. Clic secundario / derecho (Right-Click: btn == 2) -> Abrir menú contextual
            if btn == 2:
                self._open_context_menu(x, y, sidebar_w)
                return

            # 0b. Movimiento de cursor sin clic (Hover: btn == 35)
            if btn == 35:
                btn_y_min, btn_y_max = self._button_row_range

                # Hover sobre barra lateral izquierda
                if x <= sidebar_w:
                    sec_idx = self._sidebar_click_map.get(y)
                    self.hover_sidebar_idx = sec_idx
                    self.hover_item_idx = None
                    self.hover_subcontrol = None
                    self.hover_button_key = None
                    if sec_idx is not None and 0 <= sec_idx < len(active_sections):
                        _, _, _, s_title, s_desc = active_sections[sec_idx]
                        self.status_message = f"{s_title}: {s_desc}"
                    return

                # Hover sobre los botones inferiores 3D
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
                        if self.view_mode == "theme_creator":
                            self.cancel_changes()
                        else:
                            self.running = False
                    return

                btn_y_min, btn_y_max = self._button_row_range
                if x > sidebar_w + 1 and btn_y_min <= y <= btn_y_max:
                    reset_r = self._button_click_map.get("reset")
                    cancel_r = self._button_click_map.get("cancel")
                    save_r = self._button_click_map.get("save")

                    if reset_r and reset_r[0] <= x <= reset_r[1] and self.view_mode != "theme_creator":
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
                        if self.view_mode == "theme_creator":
                            self.cancel_changes()
                        else:
                            self.running = False
                    elif x <= 16:
                        if self.active_pane == "sidebar":
                            self.active_pane = "content"
                        elif self.active_pane == "content":
                            self.active_pane = "buttons"
                            if self.view_mode == "theme_creator" and self.selected_button_idx == 0:
                                self.selected_button_idx = 2
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

                        elif item.item_type == "action":
                            c_start, c_end = info["control_range"]
                            if c_start <= x <= c_end or item.key.startswith("keybind:item:"):
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

            # 3. Rueda del ratón hacia arriba (Scroll Up: btn == 64) — solo navega la lista, nunca altera el valor
            elif btn == 64:
                if x <= sidebar_w:
                    self._request_section_change(self.current_section_idx - 1, focus_content=False)
                else:
                    self._move_content_selection(-1)

            # 4. Rueda del ratón hacia abajo (Scroll Down: btn == 65) — solo navega la lista, nunca altera el valor
            elif btn == 65:
                if x <= sidebar_w:
                    self._request_section_change(self.current_section_idx + 1, focus_content=False)
                else:
                    self._move_content_selection(1)

    def _adjust_current_item(self, delta: int) -> None:
        """Modifica el valor del elemento seleccionado en memoria (se aplicará al pulsar 'Aplicar')."""
        active_sections = self._get_active_sections()
        sec_id = active_sections[self.current_section_idx][1]
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

        elif item.item_type == "select" and item.options:
            valid_opts = [o for o in item.options if o not in ("Escribir #Hex...", "Escribir ruta...", "Escribir distribucion...")]
            if not valid_opts:
                return
            cur = str(self._get_item_value(item))
            try:
                idx = valid_opts.index(cur)
            except ValueError:
                idx = 0
            next_idx = (idx + delta) % len(valid_opts)
            chosen = valid_opts[next_idx]
            self._set_item_value(item.key, chosen)

        elif item.item_type == "toggle":
            cur = bool(self._get_item_value(item))
            self._set_item_value(item.key, not cur)

    def _activate_current_item(self) -> None:
        """Ejecuta la acción, abre el menú desplegable (en 'select') o conmuta el toggle del elemento seleccionado."""
        active_sections = self._get_active_sections()
        sec_id = active_sections[self.current_section_idx][1]
        items = self.section_items.get(sec_id, [])
        if not items or self.selected_item_idx >= len(items):
            return

        item = items[self.selected_item_idx]

        if item.item_type == "toggle":
            self._adjust_current_item(delta=1)
        elif item.item_type == "select":
            row_y = 5 + (self.selected_item_idx - self.content_scroll_offset) * 3
            self._open_dropdown_for_item(item, anchor_y=row_y, anchor_x=45)
        elif item.item_type in ("action", "theme_card"):
            self._execute_action(item.key)

    def _set_item_value(self, key: str, val: Any) -> None:
        """Guarda el valor en la estructura de ajustes en memoria (sin aplicar en vivo hasta pulsar 'Aplicar')."""
        if key.startswith("creator:"):
            field = key.split(":", 1)[1]
            if field == "base_theme":
                cur_name = str(self.theme_creator_spec.get("name", "mi-tema-omarchy"))
                new_spec = self.theme_engine.get_theme_full_spec(str(val))
                new_spec["name"] = cur_name
                new_spec["base_theme"] = str(val)
                self.theme_creator_spec.update(new_spec)
                self.status_message = f"Plantilla '{val}' cargada."
            elif field == "widget_alpha":
                self.theme_creator_spec["widget_alpha"] = float(val)
            else:
                self.theme_creator_spec[field] = str(val)
            return

        if key.startswith("autostart:item:"):
            idx = int(key.split(":")[-1])
            if 0 <= idx < len(self.autostart_items):
                self.autostart_items[idx]["enabled"] = bool(val)
                self._sync_autostart_into_settings()
            return

        if key.startswith("bar_widget:"):
            s_key = key.split(":", 1)[1]
            self.settings[s_key] = str(val)
            self.status_message = f"Widget '{val}' seleccionado."
            return

        if key == "input:kb_layout":
            self.settings["kb_layout"] = str(val)
            for it in self.section_items.get("devices", []):
                if it.key == "input:kb_layout" and str(val) not in it.options:
                    it.options.insert(0, str(val))
            return

        if key == "input:kb_variant":
            self.settings["kb_variant"] = "" if str(val) == "none" else str(val)
            return

        if key == "input:kb_model":
            self.settings["kb_model"] = str(val)
            return

        if key == "input:kb_grp_toggle":
            self.settings["kb_grp_toggle"] = "Ninguno" if str(val) in ("none", "Ninguno", "") else str(val)
            return

        if key == "input:compose_key":
            val_str = str(val)
            if "Pulsar tecla" in val_str:
                self._start_compose_recording()
                return
            if "Desactivada" in val_str or "none" in val_str:
                self.settings["compose_key"] = "none"
            elif "Bloq May" in val_str or "Caps" in val_str:
                self.settings["compose_key"] = "caps"
            elif "Menú" in val_str or "Menu" in val_str:
                self.settings["compose_key"] = "menu"
            elif "Derecho" in val_str or "rwin" in val_str:
                self.settings["compose_key"] = "rwin"
            elif "Izquierdo" in val_str or "lwin" in val_str:
                self.settings["compose_key"] = "lwin"
            elif "Impr" in val_str or "PrtSc" in val_str:
                self.settings["compose_key"] = "prsc"
            elif "Insert" in val_str:
                self.settings["compose_key"] = "ins"
            elif "Pausa" in val_str or "Pause" in val_str:
                self.settings["compose_key"] = "paus"
            elif "Alt Gr" in val_str:
                self.settings["compose_key"] = "ralt"
            else:
                self.settings["compose_key"] = "none"

            self.saved_settings["compose_key"] = self.settings["compose_key"]
            self.config_sync.fix_caps_lock(compose_key=self.settings["compose_key"])
            self.status_message = "✓ Tecla Compose actualizada."
            return

        if key == "cursor:theme":
            self.settings["cursor_theme"] = str(val)
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
            s_val = str(val).strip()
            first_ch = s_val[0] if s_val else "0"
            self.settings["monitor_transform"] = int(first_ch) if first_ch.isdigit() else 0
            return

        if key == "display:gdk_scale":
            self.settings["monitor_gdk_scale"] = int(val)
            return

        if key == "display:vrr":
            s_val = str(val).strip()
            first_ch = s_val[0] if s_val else "0"
            self.settings["monitor_vrr"] = int(first_ch) if first_ch.isdigit() else 0
            return

        if key == "omarchy:theme":
            self.settings["omarchy_theme_name"] = str(val)
            self.section_items["themes"] = self._build_themes_section_items()
            self.status_message = f"Tema '{val}' seleccionado."
            return

        if key in self.KEY_TO_SETTING:
            s_key, caster, _ = self.KEY_TO_SETTING[key]
            self.settings[s_key] = caster(val)
        else:
            self.settings[key] = val

    def _execute_action(self, action_key: str) -> None:
        """Ejecuta acciones especiales como modales de autostart, atajos, estudio de creación/edición de temas o utilidades."""
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

        elif action_key == "action:add_keybind":
            self.modal_state = "add_keybind"
            self.modal_kb_idx = -1
            self.modal_kb_tab = "program"
            self.modal_kb_field = 0
            self.modal_kb_keys = "SUPER + "
            self.modal_kb_action = ""
            self.modal_kb_desc = "Nuevo atajo"
            self.modal_kb_app_extra = ""
            self.modal_kb_app_selected_cmd = ""
            self.modal_kb_app_selected_name = ""
            self.modal_kb_app_idx = 0
            self.modal_kb_app_scroll = 0
            self.modal_kb_app_search = ""
            self.modal_kb_app_dropdown_open = False
            self.modal_selected_idx = 1
            if not self.installed_apps:
                self.installed_apps = self.config_sync.list_installed_applications()
            return

        elif action_key.startswith("keybind:item:"):
            kb_idx = int(action_key.split(":")[-1])
            self._open_keybind_modal(kb_idx, initial_field=0)
            return

        elif action_key == "action:create_theme":
            self._prev_main_section_idx = self.current_section_idx
            base_t = self.theme_engine.current_theme
            self.theme_creator_spec = self.theme_engine.get_theme_full_spec(base_t)
            self.theme_creator_spec["name"] = "mi-tema-omarchy"
            self.theme_creator_spec["base_theme"] = base_t
            self.creator_is_editing = False
            self.creator_editing_slug = ""
            for _, c_sec_id, _, _, _ in self.CREATOR_SECTIONS:
                self.section_items[c_sec_id] = self._build_creator_section_items(c_sec_id)
            self.view_mode = "theme_creator"
            self.current_section_idx = 0
            self.selected_item_idx = 1
            self.selected_button_idx = 2
            self.content_scroll_offset = 0
            self.active_pane = "content"
            self.status_message = "Nuevo tema: configura y pulsa 'Guardar'."
            return

        elif action_key == "action:edit_theme":
            target_t = str(self.settings.get("omarchy_theme_name", self.theme_engine.current_theme))
            self._open_theme_editor(target_t)
            return

        elif action_key == "action:clone_theme":
            self._prev_main_section_idx = self.current_section_idx
            base_t = str(self.settings.get("omarchy_theme_name", self.theme_engine.current_theme))
            self.theme_creator_spec = self.theme_engine.get_theme_full_spec(base_t)
            self.theme_creator_spec["name"] = f"{base_t}-custom"
            self.theme_creator_spec["base_theme"] = base_t
            self.creator_is_editing = False
            self.creator_editing_slug = ""
            for _, c_sec_id, _, _, _ in self.CREATOR_SECTIONS:
                self.section_items[c_sec_id] = self._build_creator_section_items(c_sec_id)
            self.view_mode = "theme_creator"
            self.current_section_idx = 0
            self.selected_item_idx = 1
            self.selected_button_idx = 2
            self.content_scroll_offset = 0
            self.active_pane = "content"
            self.status_message = f"Duplicando '{base_t}': personaliza y pulsa 'Guardar'."
            return

        elif action_key == "action:delete_theme":
            target_t = str(self.settings.get("omarchy_theme_name", self.theme_engine.current_theme))
            self._prompt_delete_theme(target_t)
            return

        elif action_key == "creator:name":
            self.modal_state = "input_creator_text"
            self.modal_text_target = "creator:name"
            self.modal_input_text = str(self.theme_creator_spec.get("name", "mi-tema-omarchy"))
            self.modal_selected_idx = 1
            return

        elif action_key.startswith("user_theme:item:"):
            target_slug = action_key.split(":", 2)[-1]
            self._set_item_value("omarchy:theme", target_slug)
            return

        elif action_key == "action:reset_bar_defaults":
            if self.config_sync.reset_bar_defaults(self.settings):
                self.saved_settings = dict(self.settings)
                self.section_items["bar"] = self._build_bar_section_items()
                self.status_message = "✓ Barra superior restaurada."
            else:
                self.status_message = "Error al restaurar barra."
            return

        elif action_key == "action:restart_shell":
            try:
                subprocess.Popen(
                    ["omarchy-restart-shell"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.status_message = "✓ Reiniciando barra superior..."
            except Exception:
                self.status_message = "No se encontró 'omarchy-restart-shell'."
            return

        elif action_key == "action:record_compose":
            self._start_compose_recording()
            return

        elif action_key == "action:fix_caps":
            self.settings["compose_key"] = "none"
            self.settings["kb_grp_toggle"] = "Ninguno"
            self.config_sync.fix_caps_lock(compose_key="none")
            self.config_sync.save_gui_settings(self.settings, apply_live=True)
            self.saved_settings["compose_key"] = "none"
            self.saved_settings["kb_grp_toggle"] = "Ninguno"
            self.status_message = "✓ Tecla Bloq Mayus y Alt Gr (@) restauradas."
            return

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
                self.status_message = f"✓ Monitor {m_name} guardado."
            else:
                self.status_message = "Error al guardar monitor."

        elif action_key == "action:next_wallpaper":
            try:
                subprocess.Popen(
                    ["omarchy-theme-bg-next"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.status_message = "✓ Fondo cambiado."
            except Exception:
                self.status_message = "No se encontró 'omarchy-theme-bg-next'."

        elif action_key == "action:toggle_bar":
            try:
                subprocess.Popen(
                    ["omarchy-toggle-bar"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.settings["bar_visible"] = not bool(self.settings.get("bar_visible", True))
                self.saved_settings["bar_visible"] = self.settings["bar_visible"]
                self.status_message = "✓ Barra alternada."
            except Exception:
                self.status_message = "No se encontró 'omarchy-toggle-bar'."

        elif action_key == "action:toggle_nightlight":
            try:
                subprocess.Popen(
                    ["omarchy-toggle-nightlight"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.status_message = "✓ Luz nocturna alternada."
            except Exception:
                self.status_message = "No se encontró 'omarchy-toggle-nightlight'."

    def _has_bar_changes(self) -> bool:
        """Verifica si se modificaron opciones de la barra superior de Omarchy."""
        return any(
            k.startswith("bar_") and self.settings.get(k) != self.saved_settings.get(k)
            for k in self.settings
        )

    def save_all(self) -> None:
        """
        En la ventana de creación/edición de temas ('theme_creator'), guarda el tema en
        /home/leonardo/.config/omarchy/themes/<slug> y regresa a la ventana de configuración.
        En la ventana principal ('main'), aplica y guarda todos los cambios.
        """
        if self.view_mode == "theme_creator":
            self.status_message = "Guardando tema..."
            self.render()
            new_slug = self.theme_engine.normalize_theme_slug(
                str(self.theme_creator_spec.get("name", "mi-tema-omarchy"))
            )
            cur_active_slug = self.theme_engine.normalize_theme_slug(self.theme_engine.current_theme)
            should_activate = (new_slug == cur_active_slug) or (
                self.creator_is_editing and self.creator_editing_slug == cur_active_slug
            )
            ok, msg = self.theme_engine.create_theme_from_spec(
                self.theme_creator_spec, activate=should_activate
            )
            if ok:
                # Si el usuario renombró un tema de usuario al editarlo, limpiar el slug anterior
                if (
                    self.creator_is_editing
                    and self.creator_editing_slug
                    and self.creator_editing_slug != new_slug
                ):
                    user_slugs = {
                        self.theme_engine.normalize_theme_slug(u)
                        for u in self.theme_engine.list_user_themes()
                    }
                    if self.creator_editing_slug in user_slugs:
                        self.theme_engine.delete_user_theme(self.creator_editing_slug)

                self.available_themes = self.theme_engine.list_available_themes()
                self.settings["omarchy_theme_name"] = new_slug
                self.creator_is_editing = False
                self.creator_editing_slug = ""
                self.view_mode = "main"
                self.section_items = self._init_section_items()
                self.current_section_idx = self._prev_main_section_idx
                self.selected_item_idx = 0
                self.content_scroll_offset = 0
                self.active_pane = "content"
                self.status_message = msg
            else:
                self.status_message = f"Error: {msg}"
            return

        ok_gui = self.config_sync.save_gui_settings(self.settings, apply_live=True)
        ok_auto = self.config_sync.save_autostart_items(self.autostart_items)
        ok_kb = self.config_sync.save_keybinds(self.keybind_items)

        if self._has_bar_changes():
            self.config_sync.save_bar_settings(self.settings, reload_shell=True)

        if self.settings.get("compose_key") != self.saved_settings.get("compose_key"):
            self.config_sync.fix_caps_lock(compose_key=str(self.settings.get("compose_key", "none")))

        if self.settings.get("omarchy_theme_name") != self.saved_settings.get("omarchy_theme_name"):
            chosen_theme = str(self.settings.get("omarchy_theme_name", self.theme_engine.current_theme))
            self.status_message = f"Activando tema '{chosen_theme}'..."
            self.render()
            self.theme_engine.set_theme(chosen_theme)
            self._sync_theme_into_settings()
            self.section_items = self._init_section_items()

        if ok_gui and ok_auto and ok_kb:
            self._sync_keybinds_into_settings()
            self.saved_settings = dict(self.settings)
            self.saved_autostart = [dict(x) for x in self.autostart_items]
            self.saved_keybinds = [dict(x) for x in self.keybind_items]
            self.status_message = "✓ Cambios aplicados."
        else:
            self.status_message = "Error al aplicar configuracion."

    def cancel_changes(self) -> None:
        """
        En la ventana de creación de temas ('theme_creator'), regresa a la ventana principal.
        En la ventana principal ('main'), descarta los cambios en memoria y cierra la aplicación.
        """
        if self.view_mode == "theme_creator":
            self.view_mode = "main"
            self.creator_is_editing = False
            self.creator_editing_slug = ""
            self.current_section_idx = self._prev_main_section_idx
            self.selected_item_idx = 0
            self.content_scroll_offset = 0
            self.active_pane = "content"
            self.status_message = "Edicion cancelada."
            return

        self.settings = dict(self.saved_settings)
        self.autostart_items = [dict(x) for x in self.saved_autostart]
        self.keybind_items = [dict(x) for x in self.saved_keybinds]
        self.running = False

    def reset_to_defaults(self) -> None:
        """Abre la ventana de confirmación antes de restablecer los ajustes a valores por defecto."""
        self.modal_state = "confirm_reset"
        self.modal_selected_idx = 1  # Por defecto en 'Confirmar' (0: Cancelar, 1: Confirmar)

    def _perform_reset_to_defaults(self) -> None:
        """Ejecuta el restablecimiento real tras la confirmación del usuario."""
        if self.view_mode == "theme_creator":
            base_t = str(self.theme_creator_spec.get("base_theme", self.theme_engine.current_theme))
            cur_name = str(self.theme_creator_spec.get("name", "mi-tema-omarchy"))
            self.theme_creator_spec = self.theme_engine.get_theme_full_spec(base_t)
            self.theme_creator_spec["name"] = cur_name
            self.theme_creator_spec["base_theme"] = base_t
            self.status_message = f"✓ Parametros del tema restablecidos a la plantilla '{base_t}'."
            return

        defaults = self.config_sync.get_default_settings()
        self.settings.update(defaults)
        self.keybind_items = self.config_sync.get_default_keybinds()
        self._sync_theme_into_settings()
        self._sync_autostart_into_settings()
        self._sync_keybinds_into_settings()
        self.config_sync.save_gui_settings(self.settings, apply_live=True)
        self.config_sync.save_keybinds(self.keybind_items)
        self.saved_settings = dict(self.settings)
        self.saved_keybinds = [dict(x) for x in self.keybind_items]
        self.section_items = self._init_section_items()
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

