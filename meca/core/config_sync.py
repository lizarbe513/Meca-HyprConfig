"""
Módulo de Sincronización y Persistencia de Configuraciones en Archivos Lua de Hyprland
y Configuración de la Barra Superior de Omarchy (~/.config/omarchy/shell.json).
Garantiza persistencia completa en hyprland-gui.lua, autostart.lua, input.lua, monitors.lua,
hyprland.lua y shell.json.
"""

from __future__ import annotations
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List
from meca.core.hypr_ipc import HyprIPC


class ConfigSync:
    # Widgets nativos de la barra superior de Omarchy (id, clave en settings, etiqueta, sección por defecto)
    BAR_WIDGETS = [
        ("omarchy.menu", "bar_w_menu", "Menú Omarchy (Logo)", "left"),
        ("omarchy.network", "bar_w_network", "Red / Wi-Fi", "left"),
        ("omarchy.active-window", "bar_w_active_window", "Título de ventana activa", "off"),
        ("omarchy.keyboard-layout", "bar_w_keyboard", "Distribución de teclado", "center"),
        ("omarchy.workspaces", "bar_w_workspaces", "Espacios de trabajo (Workspaces)", "center"),
        ("omarchy.clock", "bar_w_clock", "Reloj y fecha", "center"),
        ("omarchy.media", "bar_w_media", "Reproductor multimedia", "off"),
        ("omarchy.indicators", "bar_w_indicators", "Indicadores de grabación / estado", "center"),
        ("omarchy.system-update", "bar_w_updates", "Actualizaciones del sistema", "center"),
        ("omarchy.weather", "bar_w_weather", "Clima (Weather)", "center"),
        ("omarchy.tray", "bar_w_tray", "Bandeja del sistema (System Tray)", "right"),
        ("omarchy.agents", "bar_w_agents", "Agentes activos", "right"),
        ("omarchy.bluetooth", "bar_w_bluetooth", "Bluetooth", "right"),
        ("omarchy.audio", "bar_w_audio", "Volumen de audio", "right"),
        ("omarchy.microphone", "bar_w_microphone", "Micrófono", "off"),
        ("omarchy.monitor", "bar_w_monitor", "Brillo / Pantalla", "right"),
        ("omarchy.power", "bar_w_power", "Menú de energía / Batería", "right"),
        ("omarchy.tailscale", "bar_w_tailscale", "Tailscale VPN", "off"),
        ("omarchy.dropbox", "bar_w_dropbox", "Dropbox", "off"),
    ]

    # Catálogo completo de los atajos del sistema Omarchy/Hyprland (categoría, id, nombre, teclas_vista, teclas_lua, expresion_lua, comando_editable)
    DEFAULT_SYSTEM_KEYBINDS = [
        # APLICACIONES Y WEBAPPS (applications.lua)
        ("APLICACIONES", "app_terminal", "Terminal", "SUPER + RETURN", "SUPER + RETURN", '{ omarchy = "terminal" }', "omarchy-launch-terminal"),
        ("APLICACIONES", "app_browser", "Navegador web", "SUPER + SHIFT + RETURN", "SUPER + SHIFT + RETURN", '{ omarchy = "browser" }', "omarchy-launch-browser"),
        ("APLICACIONES", "app_browser_b", "Navegador (Alt)", "SUPER + SHIFT + B", "SUPER + SHIFT + B", '{ omarchy = "browser" }', "omarchy-launch-browser"),
        ("APLICACIONES", "app_browser_priv", "Navegador privado", "SUPER + SHIFT + ALT + B", "SUPER + SHIFT + ALT + B", '{ omarchy = "browser --private" }', "omarchy-launch-browser --private"),
        ("APLICACIONES", "app_files", "Gestor de archivos", "SUPER + SHIFT + F", "SUPER + SHIFT + F", '{ omarchy = "nautilus" }', "omarchy-launch-nautilus"),
        ("APLICACIONES", "app_files_cwd", "Archivos (carpeta actual)", "SUPER + ALT + SHIFT + F", "SUPER + ALT + SHIFT + F", '{ omarchy = "nautilus-cwd" }', "omarchy-launch-nautilus-cwd"),
        ("APLICACIONES", "app_editor", "Editor de codigo", "SUPER + SHIFT + N", "SUPER + SHIFT + N", '{ omarchy = "editor" }', "omarchy-launch-editor"),
        ("APLICACIONES", "app_tmux", "Terminal Tmux", "SUPER + ALT + RETURN", "SUPER + ALT + RETURN", '{ omarchy = "terminal-tmux" }', "omarchy-launch-terminal-tmux"),
        ("APLICACIONES", "app_herdr", "Terminal Herdr", "SUPER + CTRL + RETURN", "SUPER + CTRL + RETURN", '{ omarchy = "terminal-herdr" }', "omarchy-launch-terminal-herdr"),
        ("APLICACIONES", "app_music", "Musica (Spotify)", "SUPER + SHIFT + M", "SUPER + SHIFT + M", '{ omarchy = "spotify" }', "omarchy-launch-spotify"),
        ("APLICACIONES", "app_music_tui", "Musica TUI (Cliamp)", "SUPER + SHIFT + ALT + M", "SUPER + SHIFT + ALT + M", '{ tui = "cliamp", focus = true }', "omarchy-launch-or-focus-tui cliamp"),
        ("APLICACIONES", "app_docker", "Docker TUI", "SUPER + SHIFT + D", "SUPER + SHIFT + D", '{ tui = "omarchy-launch-docker-tui" }', "omarchy-launch-tui omarchy-launch-docker-tui"),
        ("APLICACIONES", "app_signal", "Signal", "SUPER + SHIFT + G", "SUPER + SHIFT + G", '{ omarchy = "signal" }', "omarchy-launch-signal"),
        ("APLICACIONES", "app_obsidian", "Obsidian", "SUPER + SHIFT + O", "SUPER + SHIFT + O", '{ launch = "obsidian", focus = "^obsidian$" }', "uwsm-app -- obsidian"),
        ("APLICACIONES", "app_omawrite", "Omawrite", "SUPER + SHIFT + W", "SUPER + SHIFT + W", '{ launch = "omawrite" }', "uwsm-app -- omawrite"),
        ("APLICACIONES", "app_passwords", "Contraseñas (1Password)", "SUPER + SHIFT + SLASH", "SUPER + SHIFT + SLASH", '{ omarchy = "1password" }', "omarchy-launch-1password"),
        ("APLICACIONES", "app_chatgpt", "ChatGPT", "SUPER + SHIFT + A", "SUPER + SHIFT + A", '{ webapp = "https://chatgpt.com" }', "omarchy-launch-webapp https://chatgpt.com"),
        ("APLICACIONES", "app_grok", "Grok", "SUPER + SHIFT + ALT + A", "SUPER + SHIFT + ALT + A", '{ webapp = "https://grok.com" }', "omarchy-launch-webapp https://grok.com"),
        ("APLICACIONES", "app_calendar_web", "Calendario Web", "SUPER + SHIFT + C", "SUPER + SHIFT + C", '{ webapp = "https://app.hey.com/calendar/weeks/" }', "omarchy-launch-webapp https://app.hey.com/calendar/weeks/"),
        ("APLICACIONES", "app_email", "Correo Web", "SUPER + SHIFT + E", "SUPER + SHIFT + E", '{ webapp = "https://app.hey.com" }', "omarchy-launch-webapp https://app.hey.com"),
        ("APLICACIONES", "app_youtube", "YouTube", "SUPER + SHIFT + Y", "SUPER + SHIFT + Y", '{ webapp = "https://youtube.com/" }', "omarchy-launch-webapp https://youtube.com/"),
        ("APLICACIONES", "app_whatsapp", "WhatsApp", "SUPER + SHIFT + ALT + G", "SUPER + SHIFT + ALT + G", '{ webapp = "https://web.whatsapp.com/", focus = true }', "omarchy-launch-webapp https://web.whatsapp.com/"),
        ("APLICACIONES", "app_gmessages", "Google Messages", "SUPER + SHIFT + CTRL + G", "SUPER + SHIFT + CTRL + G", '{ webapp = "https://messages.google.com/web/conversations", focus = true }', "omarchy-launch-webapp https://messages.google.com/web/conversations"),
        ("APLICACIONES", "app_gphotos", "Google Photos", "SUPER + SHIFT + P", "SUPER + SHIFT + P", '{ webapp = "https://photos.google.com/", focus = true }', "omarchy-launch-webapp https://photos.google.com/"),
        ("APLICACIONES", "app_gmaps", "Google Maps", "SUPER + SHIFT + S", "SUPER + SHIFT + S", '{ webapp = "https://maps.google.com/", focus = true }', "omarchy-launch-webapp https://maps.google.com/"),
        ("APLICACIONES", "app_x", "X (Twitter)", "SUPER + SHIFT + X", "SUPER + SHIFT + X", '{ webapp = "https://x.com/" }', "omarchy-launch-webapp https://x.com/"),
        # MENUS Y UTILIDADES OMARCHY (utilities.lua)
        ("MENUS Y UTILIDADES", "util_omarchy_menu", "Menu Omarchy", "SUPER + SPACE", "SUPER + SPACE", '"omarchy-menu toggle"', "omarchy-menu toggle"),
        ("MENUS Y UTILIDADES", "util_apps_menu", "Lanzador de apps", "SUPER + ALT + SPACE", "SUPER + ALT + SPACE", '"omarchy-menu toggle apps"', "omarchy-menu toggle apps"),
        ("MENUS Y UTILIDADES", "util_system_menu", "Menu de sistema", "SUPER + ESCAPE", "SUPER + ESCAPE", '"omarchy-menu toggle system"', "omarchy-menu toggle system"),
        ("MENUS Y UTILIDADES", "util_theme_menu", "Menu de temas", "SUPER + SHIFT + CTRL + SPACE", "SUPER + SHIFT + CTRL + SPACE", '"omarchy-menu toggle theme"', "omarchy-menu toggle theme"),
        ("MENUS Y UTILIDADES", "util_bg_menu", "Cambiar fondo", "SUPER + CTRL + SPACE", "SUPER + CTRL + SPACE", '"omarchy-menu toggle background"', "omarchy-menu toggle background"),
        ("MENUS Y UTILIDADES", "util_toggle_bar", "Alternar barra superior", "SUPER + SHIFT + SPACE", "SUPER + SHIFT + SPACE", '"omarchy-toggle-bar"', "omarchy-toggle-bar"),
        ("MENUS Y UTILIDADES", "util_capture_menu", "Menu de captura", "SUPER + CTRL + C", "SUPER + CTRL + C", '"omarchy-menu toggle capture"', "omarchy-menu toggle capture"),
        ("MENUS Y UTILIDADES", "util_toggle_menu", "Menu de ajustes rapidos", "SUPER + CTRL + O", "SUPER + CTRL + O", '"omarchy-menu toggle toggle"', "omarchy-menu toggle toggle"),
        ("MENUS Y UTILIDADES", "util_hw_menu", "Menu de hardware", "SUPER + CTRL + H", "SUPER + CTRL + H", '"omarchy-menu toggle hardware"', "omarchy-menu toggle hardware"),
        ("MENUS Y UTILIDADES", "util_keybinds", "Lista de atajos", "SUPER + K", "SUPER + K", '"omarchy-menu-keybindings"', "omarchy-menu-keybindings"),
        ("MENUS Y UTILIDADES", "util_tmux_keys", "Atajos de Tmux", "SUPER + ALT + K", "SUPER + ALT + K", '"omarchy-menu-tmux-keybindings"', "omarchy-menu-tmux-keybindings"),
        ("MENUS Y UTILIDADES", "util_herdr_keys", "Atajos de Herdr", "SUPER + CTRL + K", "SUPER + CTRL + K", '"omarchy-menu-herdr-keybindings"', "omarchy-menu-herdr-keybindings"),
        ("MENUS Y UTILIDADES", "util_calc", "Calculadora", "SUPER + CTRL + Q", "SUPER + CTRL + Q", '"omacalc"', "omacalc"),
        ("MENUS Y UTILIDADES", "util_emojis", "Selector de emojis", "SUPER + CTRL + E", "SUPER + CTRL + E", '"omarchy-shell shell toggle omarchy.emojis"', "omarchy-shell shell toggle omarchy.emojis"),
        ("MENUS Y UTILIDADES", "util_screenshot", "Captura de pantalla", "PRINT", "PRINT", '"omarchy-capture-screenshot"', "omarchy-capture-screenshot"),
        ("MENUS Y UTILIDADES", "util_screenrec", "Grabar pantalla", "ALT + PRINT", "ALT + PRINT", '"omarchy-capture-screenrecording --stop-recording || omarchy-menu toggle trigger.capture.screenrecord"', "omarchy-capture-screenrecording --stop-recording || omarchy-menu toggle trigger.capture.screenrecord"),
        ("MENUS Y UTILIDADES", "util_colorpicker", "Selector de color", "SUPER + PRINT", "SUPER + PRINT", '"pkill hyprpicker || hyprpicker -a"', "pkill hyprpicker || hyprpicker -a"),
        ("MENUS Y UTILIDADES", "util_ocr", "Extraer texto (OCR)", "SUPER + CTRL + PRINT", "SUPER + CTRL + PRINT", '"omarchy-capture-text"', "omarchy-capture-text"),
        ("MENUS Y UTILIDADES", "util_share", "Compartir (LocalSend)", "SUPER + CTRL + S", "SUPER + CTRL + S", '"omarchy-menu toggle share"', "omarchy-menu toggle share"),
        ("MENUS Y UTILIDADES", "util_lock", "Bloquear sesion", "SUPER + CTRL + L", "SUPER + CTRL + L", '"omarchy-system-lock"', "omarchy-system-lock"),
        ("MENUS Y UTILIDADES", "util_idle", "Alternar autobloqueo", "SUPER + CTRL + I", "SUPER + CTRL + I", '"omarchy-toggle-idle"', "omarchy-toggle-idle"),
        ("MENUS Y UTILIDADES", "util_nightlight", "Alternar luz nocturna", "SUPER + CTRL + N", "SUPER + CTRL + N", '"omarchy-toggle-nightlight"', "omarchy-toggle-nightlight"),
        ("MENUS Y UTILIDADES", "util_audio_panel", "Panel de audio", "SUPER + CTRL + A", "SUPER + CTRL + A", '"omarchy-shell shell toggle omarchy.audio"', "omarchy-shell shell toggle omarchy.audio"),
        ("MENUS Y UTILIDADES", "util_bt_panel", "Panel Bluetooth", "SUPER + CTRL + B", "SUPER + CTRL + B", '"omarchy-shell shell toggle omarchy.bluetooth"', "omarchy-shell shell toggle omarchy.bluetooth"),
        ("MENUS Y UTILIDADES", "util_disp_panel", "Panel de pantalla", "SUPER + CTRL + D", "SUPER + CTRL + D", '"omarchy-shell shell toggle omarchy.monitor"', "omarchy-shell shell toggle omarchy.monitor"),
        ("MENUS Y UTILIDADES", "util_net_panel", "Panel de red", "SUPER + CTRL + W", "SUPER + CTRL + W", '"omarchy-shell shell toggle omarchy.network"', "omarchy-shell shell toggle omarchy.network"),
        ("MENUS Y UTILIDADES", "util_pow_panel", "Panel de energia", "SUPER + CTRL + P", "SUPER + CTRL + P", '"omarchy-shell shell toggle omarchy.power"', "omarchy-shell shell toggle omarchy.power"),
        ("MENUS Y UTILIDADES", "util_btop", "Monitor de actividad", "SUPER + CTRL + T", "SUPER + CTRL + T", '{ tui = "btop" }', "omarchy-launch-tui btop"),
        ("MENUS Y UTILIDADES", "util_notif_dismiss", "Cerrar notificacion", "SUPER + COMMA", "SUPER + comma", '"omarchy-shell notifications dismissOne"', "omarchy-shell notifications dismissOne"),
        ("MENUS Y UTILIDADES", "util_notif_all", "Cerrar todas las notif.", "SUPER + SHIFT + COMMA", "SUPER + SHIFT + comma", '"omarchy-shell notifications dismissAll"', "omarchy-shell notifications dismissAll"),
        ("MENUS Y UTILIDADES", "util_notif_silence", "Silenciar notificaciones", "SUPER + CTRL + COMMA", "SUPER + CTRL + comma", '"omarchy-toggle-notification-silencing"', "omarchy-toggle-notification-silencing"),
        ("MENUS Y UTILIDADES", "util_notif_hist", "Historial notificaciones", "SUPER + SHIFT + ALT + COMMA", "SUPER + SHIFT + ALT + comma", '"omarchy-shell notifications showHistory"', "omarchy-shell notifications showHistory"),
        # VENTANAS Y TILING (tiling.lua)
        ("VENTANAS Y TILING", "win_close", "Cerrar ventana", "SUPER + W", "SUPER + W", "hl.dsp.window.close()", "hl.dsp.window.close()"),
        ("VENTANAS Y TILING", "win_close_all", "Cerrar todas las ventanas", "CTRL + ALT + DELETE", "CTRL + ALT + DELETE", '"omarchy-hyprland-window-close-all"', "omarchy-hyprland-window-close-all"),
        ("VENTANAS Y TILING", "win_split", "Alternar division", "SUPER + J", "SUPER + J", 'hl.dsp.layout("togglesplit")', 'hl.dsp.layout("togglesplit")'),
        ("VENTANAS Y TILING", "win_pseudo", "Modo pseudo-tiling", "SUPER + P", "SUPER + P", "hl.dsp.window.pseudo()", "hl.dsp.window.pseudo()"),
        ("VENTANAS Y TILING", "win_float", "Alternar flotante/mosaico", "SUPER + T", "SUPER + T", 'hl.dsp.window.float({ action = "toggle" })', 'hl.dsp.window.float({ action = "toggle" })'),
        ("VENTANAS Y TILING", "win_fullscreen", "Pantalla completa", "SUPER + F", "SUPER + F", 'hl.dsp.window.fullscreen({ mode = "fullscreen" })', 'hl.dsp.window.fullscreen({ mode = "fullscreen" })'),
        ("VENTANAS Y TILING", "win_tiled_fs", "Pantalla completa en mosaico", "SUPER + CTRL + F", "SUPER + CTRL + F", '"omarchy-hyprland-window-tiled-fullscreen-toggle"', "omarchy-hyprland-window-tiled-fullscreen-toggle"),
        ("VENTANAS Y TILING", "win_fullwidth", "Maximizar ancho", "SUPER + ALT + F", "SUPER + ALT + F", 'hl.dsp.window.fullscreen({ mode = "maximized" })', 'hl.dsp.window.fullscreen({ mode = "maximized" })'),
        ("VENTANAS Y TILING", "win_pop", "Fijar ventana flotante", "SUPER + O", "SUPER + O", '"omarchy-hyprland-window-pop"', "omarchy-hyprland-window-pop"),
        ("VENTANAS Y TILING", "win_layout", "Alternar layout escritorio", "SUPER + L", "SUPER + L", '"omarchy-hyprland-workspace-layout-toggle"', "omarchy-hyprland-workspace-layout-toggle"),
        ("VENTANAS Y TILING", "win_transparency", "Alternar transparencia", "SUPER + BACKSPACE", "SUPER + BACKSPACE", '"omarchy-hyprland-window-transparency-toggle"', "omarchy-hyprland-window-transparency-toggle"),
        ("VENTANAS Y TILING", "win_gaps", "Alternar margenes (gaps)", "SUPER + SHIFT + BACKSPACE", "SUPER + SHIFT + BACKSPACE", '"omarchy-hyprland-window-gaps-toggle"', "omarchy-hyprland-window-gaps-toggle"),
        ("VENTANAS Y TILING", "win_focus_l", "Enfocar ventana izquierda", "SUPER + LEFT", "SUPER + LEFT", 'hl.dsp.focus({ direction = "l" })', 'hl.dsp.focus({ direction = "l" })'),
        ("VENTANAS Y TILING", "win_focus_r", "Enfocar ventana derecha", "SUPER + RIGHT", "SUPER + RIGHT", 'hl.dsp.focus({ direction = "r" })', 'hl.dsp.focus({ direction = "r" })'),
        ("VENTANAS Y TILING", "win_focus_u", "Enfocar ventana superior", "SUPER + UP", "SUPER + UP", 'hl.dsp.focus({ direction = "u" })', 'hl.dsp.focus({ direction = "u" })'),
        ("VENTANAS Y TILING", "win_focus_d", "Enfocar ventana inferior", "SUPER + DOWN", "SUPER + DOWN", 'hl.dsp.focus({ direction = "d" })', 'hl.dsp.focus({ direction = "d" })'),
        ("VENTANAS Y TILING", "win_swap_l", "Intercambiar a la izquierda", "SUPER + SHIFT + LEFT", "SUPER + SHIFT + LEFT", 'hl.dsp.window.swap({ direction = "l" })', 'hl.dsp.window.swap({ direction = "l" })'),
        ("VENTANAS Y TILING", "win_swap_r", "Intercambiar a la derecha", "SUPER + SHIFT + RIGHT", "SUPER + SHIFT + RIGHT", 'hl.dsp.window.swap({ direction = "r" })', 'hl.dsp.window.swap({ direction = "r" })'),
        ("VENTANAS Y TILING", "win_swap_u", "Intercambiar hacia arriba", "SUPER + SHIFT + UP", "SUPER + SHIFT + UP", 'hl.dsp.window.swap({ direction = "u" })', 'hl.dsp.window.swap({ direction = "u" })'),
        ("VENTANAS Y TILING", "win_swap_d", "Intercambiar hacia abajo", "SUPER + SHIFT + DOWN", "SUPER + SHIFT + DOWN", 'hl.dsp.window.swap({ direction = "d" })', 'hl.dsp.window.swap({ direction = "d" })'),
        ("VENTANAS Y TILING", "win_cycle_next", "Siguiente ventana", "ALT + TAB", "ALT + TAB", "hl.dsp.window.cycle_next()", "hl.dsp.window.cycle_next()"),
        ("VENTANAS Y TILING", "win_cycle_prev", "Ventana anterior", "ALT + SHIFT + TAB", "ALT + SHIFT + TAB", "hl.dsp.window.cycle_next({ next = false })", "hl.dsp.window.cycle_next({ next = false })"),
        ("VENTANAS Y TILING", "win_group", "Agrupar ventanas", "SUPER + G", "SUPER + G", "hl.dsp.group.toggle()", "hl.dsp.group.toggle()"),
        ("VENTANAS Y TILING", "win_ungroup", "Sacar de grupo", "SUPER + ALT + G", "SUPER + ALT + G", "hl.dsp.window.move({ out_of_group = true })", "hl.dsp.window.move({ out_of_group = true })"),
        ("VENTANAS Y TILING", "win_group_next", "Siguiente en grupo", "SUPER + ALT + TAB", "SUPER + ALT + TAB", "hl.dsp.group.next()", "hl.dsp.group.next()"),
        ("VENTANAS Y TILING", "win_group_prev", "Anterior en grupo", "SUPER + ALT + SHIFT + TAB", "SUPER + ALT + SHIFT + TAB", "hl.dsp.group.prev()", "hl.dsp.group.prev()"),
        # ESCRITORIOS (WORKSPACES)
        ("ESCRITORIOS", "ws_scratchpad", "Mostrar scratchpad", "SUPER + S", "SUPER + S", 'hl.dsp.workspace.toggle_special("scratchpad")', 'hl.dsp.workspace.toggle_special("scratchpad")'),
        ("ESCRITORIOS", "ws_to_scratch", "Enviar a scratchpad", "SUPER + ALT + S", "SUPER + ALT + S", 'hl.dsp.window.move({ workspace = "special:scratchpad", follow = false })', 'hl.dsp.window.move({ workspace = "special:scratchpad", follow = false })'),
        ("ESCRITORIOS", "ws_next", "Siguiente escritorio", "SUPER + TAB", "SUPER + TAB", 'hl.dsp.focus({ workspace = "e+1" })', 'hl.dsp.focus({ workspace = "e+1" })'),
        ("ESCRITORIOS", "ws_prev", "Escritorio anterior", "SUPER + SHIFT + TAB", "SUPER + SHIFT + TAB", 'hl.dsp.focus({ workspace = "e-1" })', 'hl.dsp.focus({ workspace = "e-1" })'),
        ("ESCRITORIOS", "ws_former", "Ultimo escritorio usado", "SUPER + CTRL + TAB", "SUPER + CTRL + TAB", 'hl.dsp.focus({ workspace = "previous" })', 'hl.dsp.focus({ workspace = "previous" })'),
        ("ESCRITORIOS", "ws_1", "Ir al escritorio 1", "SUPER + 1", "SUPER + code:10", 'hl.dsp.focus({ workspace = "1" })', 'hl.dsp.focus({ workspace = "1" })'),
        ("ESCRITORIOS", "ws_2", "Ir al escritorio 2", "SUPER + 2", "SUPER + code:11", 'hl.dsp.focus({ workspace = "2" })', 'hl.dsp.focus({ workspace = "2" })'),
        ("ESCRITORIOS", "ws_3", "Ir al escritorio 3", "SUPER + 3", "SUPER + code:12", 'hl.dsp.focus({ workspace = "3" })', 'hl.dsp.focus({ workspace = "3" })'),
        ("ESCRITORIOS", "ws_4", "Ir al escritorio 4", "SUPER + 4", "SUPER + code:13", 'hl.dsp.focus({ workspace = "4" })', 'hl.dsp.focus({ workspace = "4" })'),
        ("ESCRITORIOS", "ws_5", "Ir al escritorio 5", "SUPER + 5", "SUPER + code:14", 'hl.dsp.focus({ workspace = "5" })', 'hl.dsp.focus({ workspace = "5" })'),
        ("ESCRITORIOS", "ws_6", "Ir al escritorio 6", "SUPER + 6", "SUPER + code:15", 'hl.dsp.focus({ workspace = "6" })', 'hl.dsp.focus({ workspace = "6" })'),
        ("ESCRITORIOS", "ws_7", "Ir al escritorio 7", "SUPER + 7", "SUPER + code:16", 'hl.dsp.focus({ workspace = "7" })', 'hl.dsp.focus({ workspace = "7" })'),
        ("ESCRITORIOS", "ws_8", "Ir al escritorio 8", "SUPER + 8", "SUPER + code:17", 'hl.dsp.focus({ workspace = "8" })', 'hl.dsp.focus({ workspace = "8" })'),
        ("ESCRITORIOS", "ws_9", "Ir al escritorio 9", "SUPER + 9", "SUPER + code:18", 'hl.dsp.focus({ workspace = "9" })', 'hl.dsp.focus({ workspace = "9" })'),
        ("ESCRITORIOS", "ws_10", "Ir al escritorio 10", "SUPER + 0", "SUPER + code:19", 'hl.dsp.focus({ workspace = "10" })', 'hl.dsp.focus({ workspace = "10" })'),
        ("ESCRITORIOS", "ws_mv_1", "Mover ventana a escr. 1", "SUPER + SHIFT + 1", "SUPER + SHIFT + code:10", 'hl.dsp.window.move({ workspace = "1" })', 'hl.dsp.window.move({ workspace = "1" })'),
        ("ESCRITORIOS", "ws_mv_2", "Mover ventana a escr. 2", "SUPER + SHIFT + 2", "SUPER + SHIFT + code:11", 'hl.dsp.window.move({ workspace = "2" })', 'hl.dsp.window.move({ workspace = "2" })'),
        ("ESCRITORIOS", "ws_mv_3", "Mover ventana a escr. 3", "SUPER + SHIFT + 3", "SUPER + SHIFT + code:12", 'hl.dsp.window.move({ workspace = "3" })', 'hl.dsp.window.move({ workspace = "3" })'),
        ("ESCRITORIOS", "ws_mv_4", "Mover ventana a escr. 4", "SUPER + SHIFT + 4", "SUPER + SHIFT + code:13", 'hl.dsp.window.move({ workspace = "4" })', 'hl.dsp.window.move({ workspace = "4" })'),
        ("ESCRITORIOS", "ws_mv_5", "Mover ventana a escr. 5", "SUPER + SHIFT + 5", "SUPER + SHIFT + code:14", 'hl.dsp.window.move({ workspace = "5" })', 'hl.dsp.window.move({ workspace = "5" })'),
        # PORTAPAPELES Y MULTIMEDIA
        ("PORTAPAPELES Y MEDIA", "clip_mgr", "Gestor de portapapeles", "SUPER + CTRL + V", "SUPER + CTRL + V", '"omarchy-shell shell toggle omarchy.clipboard"', "omarchy-shell shell toggle omarchy.clipboard"),
        ("PORTAPAPELES Y MEDIA", "media_vol_up", "Subir volumen", "XF86AudioRaiseVolume", "XF86AudioRaiseVolume", '"omarchy-audio-output-volume raise"', "omarchy-audio-output-volume raise"),
        ("PORTAPAPELES Y MEDIA", "media_vol_dn", "Bajar volumen", "XF86AudioLowerVolume", "XF86AudioLowerVolume", '"omarchy-audio-output-volume lower"', "omarchy-audio-output-volume lower"),
        ("PORTAPAPELES Y MEDIA", "media_mute", "Silenciar audio", "XF86AudioMute", "XF86AudioMute", '"omarchy-audio-output-volume mute-toggle"', "omarchy-audio-output-volume mute-toggle"),
        ("PORTAPAPELES Y MEDIA", "media_mic", "Silenciar microfono", "XF86AudioMicMute", "XF86AudioMicMute", '"omarchy-audio-input-mute"', "omarchy-audio-input-mute"),
        ("PORTAPAPELES Y MEDIA", "media_bri_up", "Subir brillo", "XF86MonBrightnessUp", "XF86MonBrightnessUp", '"omarchy-brightness-display +5%"', "omarchy-brightness-display +5%"),
        ("PORTAPAPELES Y MEDIA", "media_bri_dn", "Bajar brillo", "XF86MonBrightnessDown", "XF86MonBrightnessDown", '"omarchy-brightness-display 5%-"', "omarchy-brightness-display 5%-"),
        ("PORTAPAPELES Y MEDIA", "media_play", "Reproducir / Pausar", "XF86AudioPlay", "XF86AudioPlay", '"omarchy-shell media playPause"', "omarchy-shell media playPause"),
        ("PORTAPAPELES Y MEDIA", "media_next", "Siguiente pista", "XF86AudioNext", "XF86AudioNext", '"omarchy-shell media next"', "omarchy-shell media next"),
        ("PORTAPAPELES Y MEDIA", "media_prev", "Pista anterior", "XF86AudioPrev", "XF86AudioPrev", '"omarchy-shell media previous"', "omarchy-shell media previous"),
    ]

    def __init__(self):
        self.hypr_dir = Path.home() / ".config" / "hypr"
        self.gui_file = self.hypr_dir / "hyprland-gui.lua"
        self.input_file = self.hypr_dir / "input.lua"
        self.monitors_file = self.hypr_dir / "monitors.lua"
        self.autostart_file = self.hypr_dir / "autostart.lua"
        self.bindings_file = self.hypr_dir / "bindings.lua"
        self.hyprland_file = self.hypr_dir / "hyprland.lua"
        self.shell_json_file = Path.home() / ".config" / "omarchy" / "shell.json"
        self.default_shell_json = Path("/usr/share/omarchy/config/omarchy/shell.json")
        self.bar_off_flag = Path.home() / ".local" / "state" / "omarchy" / "toggles" / "bar-off"
        self.ensure_paths()

    def ensure_paths(self) -> None:
        """Crea el directorio de configuración si no existe."""
        self.hypr_dir.mkdir(parents=True, exist_ok=True)
        self.shell_json_file.parent.mkdir(parents=True, exist_ok=True)

    def list_cursor_themes(self) -> List[str]:
        """Descubre los temas de cursor instalados en el sistema y directorio del usuario."""
        found: List[str] = ["default"]
        icon_dirs = [
            Path("/usr/share/icons"),
            Path("/usr/local/share/icons"),
            Path.home() / ".local" / "share" / "icons",
            Path.home() / ".icons",
        ]
        for root in icon_dirs:
            if not root.exists() or not root.is_dir():
                continue
            for entry in sorted(root.iterdir()):
                if entry.is_dir() and (entry / "cursors").is_dir():
                    if entry.name not in found:
                        found.append(entry.name)
        for fallback in ("Adwaita", "Yaru"):
            if fallback not in found and (Path("/usr/share/icons") / fallback).exists():
                found.append(fallback)
        return found

    def get_default_settings(self) -> Dict[str, Any]:
        """Retorna el diccionario completo de ajustes por defecto de Hyprland y Barra Omarchy."""
        defaults: Dict[str, Any] = {
            # General
            "gaps_in": 5,
            "gaps_out": 10,
            "border_size": 2,
            "resize_on_border": False,
            "extend_border_grab_area": 15,
            "hover_icon_on_border": True,
            "layout": "dwindle",
            "allow_tearing": False,
            "no_focus_fallback": False,
            "snap_enabled": False,
            "snap_window_gap": 10,
            "snap_monitor_gap": 10,
            "snap_border_overlap": False,
            # Decoration
            "rounding": 0,
            "rounding_power": 2.0,
            "active_opacity": 1.0,
            "inactive_opacity": 1.0,
            "fullscreen_opacity": 1.0,
            "dim_inactive": False,
            "dim_strength": 0.15,
            "dim_special": 0.20,
            "blur_enabled": False,
            "blur_size": 8,
            "blur_passes": 1,
            "blur_new_optimizations": True,
            "blur_xray": False,
            "blur_ignore_opacity": True,
            "blur_vibrancy": 0.17,
            "shadow_enabled": False,
            "shadow_range": 4,
            "shadow_render_power": 3,
            "shadow_sharp": False,
            # Animations
            "animations_enabled": True,
            "animations_wraparound": False,
            "animation_preset": "omarchy",
            "anim_windows": "popin 87%",
            "anim_windows_speed": 3.8,
            "anim_fade_enabled": True,
            "anim_layers": "fade",
            "anim_workspaces_enabled": False,
            "anim_workspaces": "slide",
            "anim_special": "slidevert",
            # Cursor
            "cursor_theme": "default",
            "cursor_size": 24,
            "no_hw_cursors": True,
            "cursor_timeout": 0,
            "cursor_hide_on_key": True,
            "cursor_hide_on_touch": True,
            "cursor_warp_workspace": 1,
            "cursor_zoom": 1.0,
            "cursor_zoom_rigid": False,
            # Keybinds & Keyboard Input
            "kb_layout": "es",
            "kb_variant": "",
            "kb_model": "pc105",
            "kb_grp_toggle": "Alt Izq + Alt Der",
            "compose_key": "ralt",
            "repeat_rate": 40,
            "repeat_delay": 250,
            "numlock": True,
            "omarchy_default_bindings": True,
            "omarchy_preinstalled_bindings": True,
            "binds_hide_special": True,
            "binds_workspace_back_forth": False,
            "binds_allow_cycles": False,
            # Devices (Mouse, Touchpad, Gestures)
            "follow_mouse": 1,
            "mouse_refocus": True,
            "sensitivity": 0.0,
            "accel_profile": "flat",
            "mouse_natural_scroll": False,
            "left_handed": False,
            "natural_scroll": False,
            "touchpad_scroll_factor": 0.4,
            "clickfinger": True,
            "tap_to_click": True,
            "disable_typing": True,
            "touchpad_drag_3fg": 0,
            "workspace_swipe": False,
            # Monitors & XWayland
            "monitor_scale": 1.0,
            "monitor_mode": "1920x1080@60.00Hz",
            "monitor_transform": 0,
            "monitor_gdk_scale": 1,
            "monitor_vrr": 0,
            "xwayland_zero_scaling": True,
            # Workspaces & Misc
            "workspace_count": 5,
            "workspace_layout": "dwindle",
            "misc_focus_on_activate": True,
            "misc_dpms_key": True,
            "misc_dpms_mouse": True,
            "misc_focus_under_fs": 1,
            "misc_animate_resizes": False,
            "misc_animate_dragging": False,
            # Layouts (Dwindle, Master, Scrolling, Group)
            "dwindle_force_split": 2,
            "dwindle_preserve_split": True,
            "dwindle_smart_split": False,
            "dwindle_smart_resizing": True,
            "dwindle_split_ratio": 1.0,
            "single_window_aspect": "0 0",
            "master_new_status": "master",
            "master_mfact": 0.55,
            "master_orientation": "left",
            "scrolling_column_width": 0.49,
            "groupbar_enabled": True,
            "groupbar_font_size": 12,
            "groupbar_height": 22,
            "groupbar_gradients": True,
            # Window Rules
            "rules_terminal_scroll": 1.5,
            "rules_browser_opaque": True,
            "rules_media_opaque": True,
            "rules_pavucontrol_float": True,
            "rules_calculator_float": True,
            "rules_pip_float": True,
            "rules_steam_float": True,
            "rules_localsend_float": True,
            # Barra Superior Omarchy
            "bar_visible": True,
            "bar_position": "top",
            "bar_transparent": False,
            "bar_center_anchor": "omarchy.clock",
            "bar_clock_format": "ddd d MMM h:mm AP",
            "bar_clock_alt_format": "d MMMM 'W'ww yyyy",
            "idle_screensaver": 150,
            "idle_lock": 300,
        }
        for _, s_key, _, def_sec in self.BAR_WIDGETS:
            defaults[s_key] = def_sec
        return defaults

    def load_gui_settings(self) -> Dict[str, Any]:
        """Carga los ajustes actuales desde hyprctl, archivos Lua de Hyprland y shell.json."""
        settings = self.get_default_settings()

        # 1. Consultar opciones enteras en vivo de Hyprland
        live_int_map = {
            "general:border_size": "border_size",
            "general:extend_border_grab_area": "extend_border_grab_area",
            "general:snap:window_gap": "snap_window_gap",
            "general:snap:monitor_gap": "snap_monitor_gap",
            "decoration:rounding": "rounding",
            "decoration:blur:size": "blur_size",
            "decoration:blur:passes": "blur_passes",
            "decoration:shadow:range": "shadow_range",
            "decoration:shadow:render_power": "shadow_render_power",
            "cursor:inactive_timeout": "cursor_timeout",
            "cursor:warp_on_change_workspace": "cursor_warp_workspace",
            "input:repeat_rate": "repeat_rate",
            "input:repeat_delay": "repeat_delay",
            "input:follow_mouse": "follow_mouse",
            "input:touchpad:drag_3fg": "touchpad_drag_3fg",
            "misc:on_focus_under_fullscreen": "misc_focus_under_fs",
            "dwindle:force_split": "dwindle_force_split",
            "group:groupbar:font_size": "groupbar_font_size",
            "group:groupbar:height": "groupbar_height",
            "misc:vrr": "monitor_vrr",
        }
        for hypr_k, s_k in live_int_map.items():
            val = HyprIPC.get_option(hypr_k)
            if isinstance(val, int):
                settings[s_k] = int(val)

        # 2. Consultar opciones booleanas en vivo de Hyprland
        live_bool_map = {
            "general:resize_on_border": "resize_on_border",
            "general:hover_icon_on_border": "hover_icon_on_border",
            "general:allow_tearing": "allow_tearing",
            "general:no_focus_fallback": "no_focus_fallback",
            "general:snap:enabled": "snap_enabled",
            "general:snap:border_overlap": "snap_border_overlap",
            "decoration:dim_inactive": "dim_inactive",
            "decoration:blur:enabled": "blur_enabled",
            "decoration:blur:new_optimizations": "blur_new_optimizations",
            "decoration:blur:xray": "blur_xray",
            "decoration:blur:ignore_opacity": "blur_ignore_opacity",
            "decoration:shadow:enabled": "shadow_enabled",
            "decoration:shadow:sharp": "shadow_sharp",
            "animations:enabled": "animations_enabled",
            "animations:workspace_wraparound": "animations_wraparound",
            "cursor:no_hardware_cursors": "no_hw_cursors",
            "cursor:hide_on_key_press": "cursor_hide_on_key",
            "cursor:hide_on_touch": "cursor_hide_on_touch",
            "cursor:zoom_rigid": "cursor_zoom_rigid",
            "input:numlock_by_default": "numlock",
            "input:mouse_refocus": "mouse_refocus",
            "input:natural_scroll": "mouse_natural_scroll",
            "input:left_handed": "left_handed",
            "input:touchpad:natural_scroll": "natural_scroll",
            "input:touchpad:clickfinger_behavior": "clickfinger",
            "input:touchpad:tap-to-click": "tap_to_click",
            "input:touchpad:disable_while_typing": "disable_typing",
            "binds:hide_special_on_workspace_change": "binds_hide_special",
            "binds:workspace_back_and_forth": "binds_workspace_back_forth",
            "binds:allow_workspace_cycles": "binds_allow_cycles",
            "misc:focus_on_activate": "misc_focus_on_activate",
            "misc:key_press_enables_dpms": "misc_dpms_key",
            "misc:mouse_move_enables_dpms": "misc_dpms_mouse",
            "misc:animate_manual_resizes": "misc_animate_resizes",
            "misc:animate_mouse_windowdragging": "misc_animate_dragging",
            "dwindle:preserve_split": "dwindle_preserve_split",
            "dwindle:smart_split": "dwindle_smart_split",
            "dwindle:smart_resizing": "dwindle_smart_resizing",
            "group:groupbar:enabled": "groupbar_enabled",
            "group:groupbar:gradients": "groupbar_gradients",
            "xwayland:force_zero_scaling": "xwayland_zero_scaling",
        }
        for hypr_k, s_k in live_bool_map.items():
            val = HyprIPC.get_option(hypr_k)
            if val is not None and isinstance(val, (bool, int)):
                settings[s_k] = bool(val)

        # 3. Consultar opciones flotantes en vivo de Hyprland
        live_float_map = {
            "decoration:rounding_power": "rounding_power",
            "decoration:active_opacity": "active_opacity",
            "decoration:inactive_opacity": "inactive_opacity",
            "decoration:fullscreen_opacity": "fullscreen_opacity",
            "decoration:dim_strength": "dim_strength",
            "decoration:dim_special": "dim_special",
            "decoration:blur:vibrancy": "blur_vibrancy",
            "cursor:zoom_factor": "cursor_zoom",
            "input:sensitivity": "sensitivity",
            "input:touchpad:scroll_factor": "touchpad_scroll_factor",
            "dwindle:default_split_ratio": "dwindle_split_ratio",
            "master:mfact": "master_mfact",
            "scrolling:column_width": "scrolling_column_width",
        }
        for hypr_k, s_k in live_float_map.items():
            val = HyprIPC.get_option(hypr_k)
            if val is not None:
                try:
                    settings[s_k] = round(float(val), 2)
                except (ValueError, TypeError):
                    pass

        # 4. Consultar opciones de texto en vivo de Hyprland
        live_str_map = {
            "general:layout": "layout",
            "input:kb_layout": "kb_layout",
            "input:kb_variant": "kb_variant",
            "input:kb_model": "kb_model",
            "input:accel_profile": "accel_profile",
            "master:new_status": "master_new_status",
            "master:orientation": "master_orientation",
        }
        for hypr_k, s_k in live_str_map.items():
            val = HyprIPC.get_option(hypr_k)
            if isinstance(val, str) and val.strip():
                settings[s_k] = val.strip()

        # 5. Parsear gaps (pueden venir como "5 5 5 5" en custom)
        for hypr_k, s_k in [("general:gaps_in", "gaps_in"), ("general:gaps_out", "gaps_out")]:
            g_val = HyprIPC.get_option(hypr_k)
            if isinstance(g_val, int):
                settings[s_k] = g_val
            elif isinstance(g_val, str):
                first = g_val.split()[0] if g_val.split() else ""
                if first.isdigit():
                    settings[s_k] = int(first)

        # 6. Verificar compose_key y cambio de grupo en input.lua o hyprctl
        kb_opts = HyprIPC.get_option("input:kb_options")
        if isinstance(kb_opts, str):
            if "compose:caps" in kb_opts:
                settings["compose_key"] = "caps"
            elif "compose:ralt" in kb_opts:
                settings["compose_key"] = "ralt"
            if "grp:alt_shift_toggle" in kb_opts:
                settings["kb_grp_toggle"] = "Alt + Shift"
            elif "grp:win_space_toggle" in kb_opts:
                settings["kb_grp_toggle"] = "Super + Espacio"
            elif "grp:ctrl_shift_toggle" in kb_opts:
                settings["kb_grp_toggle"] = "Ctrl + Shift"
            elif "grp:alts_toggle" in kb_opts:
                settings["kb_grp_toggle"] = "Alt Izq + Alt Der"

        # 6b. Detectar tema del cursor actual desde entorno o gsettings
        env_cursor = os.environ.get("XCURSOR_THEME") or os.environ.get("HYPRCURSOR_THEME")
        if env_cursor:
            settings["cursor_theme"] = env_cursor.strip()
        else:
            try:
                res_ct = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "cursor-theme"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if res_ct.returncode == 0 and res_ct.stdout.strip():
                    settings["cursor_theme"] = res_ct.stdout.strip().strip("'\"")
            except Exception:
                pass

        # 7. Leer metadatos guardados en hyprland-gui.lua, hyprland.lua y monitors.lua
        if self.gui_file.exists():
            try:
                gui_txt = self.gui_file.read_text(encoding="utf-8")
                m_meta = re.search(r"^--\s*MECA_META:\s*(\{.+\})\s*$", gui_txt, re.M)
                if m_meta:
                    saved_meta = json.loads(m_meta.group(1))
                    for k, v in saved_meta.items():
                        if k in settings:
                            settings[k] = v
            except Exception:
                pass

        monitors = HyprIPC.get_monitors()
        if monitors:
            m0 = monitors[0]
            settings["monitor_scale"] = round(float(m0.get("scale", 1.0) or 1.0), 2)
            w = m0.get("width", 1920)
            h = m0.get("height", 1080)
            hz = float(m0.get("refreshRate", 60.0) or 60.0)
            settings["monitor_mode"] = f"{w}x{h}@{hz:.2f}Hz"
            settings["monitor_transform"] = int(m0.get("transform", 0) or 0)

        # 8. Cargar ajustes de la barra superior de Omarchy (~/.config/omarchy/shell.json)
        self.load_bar_settings(settings)

        return settings

    # =========================================================================
    # BARRA SUPERIOR DE OMARCHY (~/.config/omarchy/shell.json)
    # =========================================================================

    def _read_shell_json_raw(self) -> Dict[str, Any]:
        target = self.shell_json_file if (self.shell_json_file.exists() and self.shell_json_file.stat().st_size > 0) else self.default_shell_json
        if target.exists():
            try:
                return json.loads(target.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "version": 1,
            "idle": {"screensaver": 150, "lock": 300},
            "bar": {
                "position": "top",
                "transparent": False,
                "centerAnchor": "omarchy.clock",
                "layout": {"left": [], "center": [], "right": []},
            },
            "plugins": [],
        }

    def load_bar_settings(self, settings: Dict[str, Any]) -> None:
        """Sincroniza el estado de ~/.config/omarchy/shell.json dentro del diccionario settings."""
        settings["bar_visible"] = not self.bar_off_flag.exists()
        data = self._read_shell_json_raw()
        bar = data.get("bar", {}) if isinstance(data.get("bar"), dict) else {}
        idle = data.get("idle", {}) if isinstance(data.get("idle"), dict) else {}

        settings["bar_position"] = str(bar.get("position", "top"))
        settings["bar_transparent"] = bool(bar.get("transparent", False))
        settings["bar_center_anchor"] = str(bar.get("centerAnchor", "omarchy.clock") or "none")
        settings["idle_screensaver"] = int(idle.get("screensaver", 150))
        settings["idle_lock"] = int(idle.get("lock", 300))

        layout = bar.get("layout", {}) if isinstance(bar.get("layout"), dict) else {}
        widget_pos: Dict[str, str] = {}
        for sec in ("left", "center", "right"):
            entries = layout.get(sec, [])
            if isinstance(entries, list):
                for entry in entries:
                    w_id = entry.get("id", "") if isinstance(entry, dict) else str(entry)
                    if w_id:
                        widget_pos[w_id] = sec
                    if w_id == "omarchy.clock" and isinstance(entry, dict):
                        if entry.get("format"):
                            settings["bar_clock_format"] = str(entry["format"])
                        if entry.get("formatAlt"):
                            settings["bar_clock_alt_format"] = str(entry["formatAlt"])

        for w_id, s_key, _, _ in self.BAR_WIDGETS:
            settings[s_key] = widget_pos.get(w_id, "off")

    def save_bar_settings(self, settings: Dict[str, Any], reload_shell: bool = True) -> bool:
        """Guarda la configuración de la barra superior en ~/.config/omarchy/shell.json y recarga el shell."""
        try:
            # 1. Visibilidad de la barra
            want_visible = bool(settings.get("bar_visible", True))
            currently_visible = not self.bar_off_flag.exists()
            if want_visible != currently_visible:
                subprocess.run(
                    ["omarchy-toggle-bar", "on" if want_visible else "off"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )

            # 2. Actualizar estructura de shell.json preservando metadatos personalizados de cada widget
            data = self._read_shell_json_raw()
            data["version"] = 1
            if not isinstance(data.get("idle"), dict):
                data["idle"] = {}
            data["idle"]["screensaver"] = int(settings.get("idle_screensaver", 150))
            data["idle"]["lock"] = int(settings.get("idle_lock", 300))

            if not isinstance(data.get("bar"), dict):
                data["bar"] = {}
            bar = data["bar"]
            bar["position"] = str(settings.get("bar_position", "top"))
            bar["transparent"] = bool(settings.get("bar_transparent", False))
            anchor = str(settings.get("bar_center_anchor", "omarchy.clock"))
            if anchor == "none":
                bar.pop("centerAnchor", None)
            else:
                bar["centerAnchor"] = anchor

            old_layout = bar.get("layout", {}) if isinstance(bar.get("layout"), dict) else {}
            existing_objs: Dict[str, Dict[str, Any]] = {}
            old_order: Dict[str, List[str]] = {"left": [], "center": [], "right": []}

            for sec in ("left", "center", "right"):
                for entry in old_layout.get(sec, []):
                    if isinstance(entry, dict) and entry.get("id"):
                        w_id = str(entry["id"])
                        existing_objs[w_id] = dict(entry)
                        old_order[sec].append(w_id)
                    elif isinstance(entry, str):
                        existing_objs[entry] = {"id": entry}
                        old_order[sec].append(entry)

            # Actualizar formato del reloj
            clock_obj = existing_objs.get("omarchy.clock", {"id": "omarchy.clock"})
            clock_obj["format"] = str(settings.get("bar_clock_format", "ddd d MMM h:mm AP"))
            clock_obj["formatAlt"] = str(settings.get("bar_clock_alt_format", "d MMMM 'W'ww yyyy"))
            clock_obj.setdefault("verticalFormat", "HH\n—\nmm")
            existing_objs["omarchy.clock"] = clock_obj

            known_ids = {w_id for w_id, _, _, _ in self.BAR_WIDGETS}
            new_layout: Dict[str, List[Dict[str, Any]]] = {"left": [], "center": [], "right": []}

            # Primero conservar el orden relativo de los widgets que ya estaban en esa sección
            for sec in ("left", "center", "right"):
                for w_id in old_order[sec]:
                    if w_id not in known_ids:
                        # Conservar widgets de plugins de terceros
                        new_layout[sec].append(existing_objs[w_id])
                    else:
                        s_key = next(k for wid, k, _, _ in self.BAR_WIDGETS if wid == w_id)
                        if settings.get(s_key, "off") == sec:
                            new_layout[sec].append(existing_objs.get(w_id, {"id": w_id}))

            # Luego agregar los widgets que fueron movidos o activados en esa sección
            for w_id, s_key, _, _ in self.BAR_WIDGETS:
                target_sec = str(settings.get(s_key, "off"))
                if target_sec in ("left", "center", "right"):
                    if not any(x.get("id") == w_id for x in new_layout[target_sec]):
                        new_layout[target_sec].append(existing_objs.get(w_id, {"id": w_id}))

            bar["layout"] = new_layout
            if not isinstance(data.get("plugins"), list):
                data["plugins"] = []

            self.shell_json_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            if reload_shell:
                subprocess.run(
                    ["omarchy-shell", "shell", "reloadConfig"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )
            return True
        except Exception:
            return False

    def reset_bar_defaults(self, settings: Dict[str, Any]) -> bool:
        """Restaura la barra superior de Omarchy a su diseño original."""
        try:
            subprocess.run(
                ["omarchy-bar", "defaults"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
            self.load_bar_settings(settings)
            return True
        except Exception:
            return False

    # =========================================================================
    # GESTIÓN DE ATAJOS DE TECLADO DEL SISTEMA (~/.config/hypr/bindings.lua)
    # =========================================================================

    def get_default_keybinds(self) -> List[Dict[str, Any]]:
        """Devuelve la lista predeterminada de atajos del sistema Omarchy como diccionarios."""
        binds: List[Dict[str, Any]] = []
        for cat, b_id, title, disp_k, lua_k, lua_expr, edit_cmd in self.DEFAULT_SYSTEM_KEYBINDS:
            binds.append({
                "id": b_id,
                "category": cat,
                "title": title,
                "keys": disp_k,
                "default_keys": disp_k,
                "orig_lua_key": lua_k,
                "default_lua_expr": lua_expr,
                "cmd": edit_cmd,
                "default_cmd": edit_cmd,
                "enabled": True,
                "is_custom": False,
            })
        return binds

    def load_keybinds(self) -> List[Dict[str, Any]]:
        """
        Carga todos los atajos del sistema Omarchy junto con las ediciones y atajos
        personalizados del usuario en ~/.config/hypr/bindings.lua.
        """
        binds = self.get_default_keybinds()
        by_id: Dict[str, Dict[str, Any]] = {entry["id"]: entry for entry in binds}

        if self.bindings_file.exists():
            try:
                txt = self.bindings_file.read_text(encoding="utf-8")
                m_meta = re.search(r"^--\s*MECA_KEYBINDS_META:\s*(\{.+\})\s*$", txt, re.M)
                if m_meta:
                    meta = json.loads(m_meta.group(1))
                    overrides = meta.get("overrides", {})
                    for b_id, ov in overrides.items():
                        if b_id in by_id and isinstance(ov, dict):
                            if "keys" in ov:
                                by_id[b_id]["keys"] = str(ov["keys"])
                            if "cmd" in ov:
                                by_id[b_id]["cmd"] = str(ov["cmd"])
                            if "enabled" in ov:
                                by_id[b_id]["enabled"] = bool(ov["enabled"])
                    for c_idx, cust in enumerate(meta.get("custom", [])):
                        if isinstance(cust, dict) and cust.get("keys") and cust.get("cmd"):
                            binds.append({
                                "id": f"custom_{c_idx}",
                                "category": "PERSONALIZADOS",
                                "title": str(cust.get("title") or cust.get("cmd")),
                                "keys": str(cust.get("keys")),
                                "default_keys": str(cust.get("keys")),
                                "orig_lua_key": str(cust.get("keys")),
                                "default_lua_expr": json.dumps(str(cust.get("cmd"))),
                                "cmd": str(cust.get("cmd")),
                                "default_cmd": str(cust.get("cmd")),
                                "enabled": bool(cust.get("enabled", True)),
                                "is_custom": True,
                            })
            except Exception:
                pass

        return binds

    @staticmethod
    def _display_key_to_lua(keys_str: str) -> str:
        """Convierte teclas de visualización (ej. SUPER + 1 o SUPER + COMMA) al formato Lua de Hyprland."""
        parts = [p.strip() for p in keys_str.split("+") if p.strip()]
        if not parts:
            return keys_str.strip()
        last = parts[-1]
        if last.isdigit() and len(last) == 1:
            num = 10 if last == "0" else int(last)
            parts[-1] = f"code:{num + 9}"
        elif last.upper() == "COMMA":
            parts[-1] = "comma"
        return " + ".join(parts)

    def save_keybinds(self, binds: List[Dict[str, Any]]) -> bool:
        """
        Persiste las modificaciones de atajos del sistema y atajos personalizados
        en ~/.config/hypr/bindings.lua usando hl.unbind(...) y o.bind(...).
        """
        overrides: Dict[str, Dict[str, Any]] = {}
        custom_list: List[Dict[str, Any]] = []
        lua_lines: List[str] = []

        for entry in binds:
            if entry.get("is_custom"):
                c_title = str(entry.get("title") or entry.get("cmd") or "Atajo")
                c_keys = str(entry.get("keys", "")).strip()
                c_cmd = str(entry.get("cmd", "")).strip()
                c_en = bool(entry.get("enabled", True))
                if not c_keys or not c_cmd:
                    continue
                custom_list.append({
                    "title": c_title,
                    "keys": c_keys,
                    "cmd": c_cmd,
                    "enabled": c_en,
                })
                if c_en:
                    lua_k = self._display_key_to_lua(c_keys)
                    expr = c_cmd if c_cmd.startswith("hl.dsp.") or c_cmd.startswith("{") else json.dumps(c_cmd)
                    lua_lines.append(f'o.bind({json.dumps(lua_k)}, {json.dumps(c_title)}, {expr})')
            else:
                b_id = str(entry.get("id", ""))
                keys = str(entry.get("keys", "")).strip()
                def_keys = str(entry.get("default_keys", "")).strip()
                orig_lua_k = str(entry.get("orig_lua_key", def_keys))
                cmd = str(entry.get("cmd", "")).strip()
                def_cmd = str(entry.get("default_cmd", "")).strip()
                def_lua_expr = str(entry.get("default_lua_expr", json.dumps(def_cmd)))
                en = bool(entry.get("enabled", True))
                title = str(entry.get("title", ""))

                changed_keys = (keys.upper() != def_keys.upper())
                changed_cmd = (cmd != def_cmd)
                if not en or changed_keys or changed_cmd:
                    overrides[b_id] = {
                        "keys": keys,
                        "cmd": cmd,
                        "enabled": en,
                    }
                    lua_lines.append(f'hl.unbind({json.dumps(orig_lua_k)})')
                    if en and keys:
                        new_lua_k = self._display_key_to_lua(keys) if changed_keys else orig_lua_k
                        if changed_cmd:
                            expr = cmd if (cmd.startswith("hl.dsp.") or cmd.startswith("{")) else json.dumps(cmd)
                        else:
                            expr = def_lua_expr
                        lua_lines.append(f'o.bind({json.dumps(new_lua_k)}, {json.dumps(title)}, {expr})')

        meta_json = json.dumps({"overrides": overrides, "custom": custom_list}, ensure_ascii=False)
        header = [
            "-- Keep only your personal keybinding overrides here. Add new bindings or",
            "-- unbind defaults before replacing them.",
            f"-- MECA_KEYBINDS_META: {meta_json}",
            "",
        ]
        try:
            self.bindings_file.write_text("\n".join(header + lua_lines) + "\n", encoding="utf-8")
            return True
        except Exception:
            return False

    # =========================================================================
    # PERSISTENCIA COMPLETA EN ARCHIVOS LUA DE HYPRLAND
    # =========================================================================

    @staticmethod
    def _b(val: Any) -> str:
        return "true" if bool(val) else "false"

    def _update_hyprland_lua_binding_flags(self, settings: Dict[str, Any]) -> None:
        """Asegura que require('hyprland-gui') esté presente en ~/.config/hypr/hyprland.lua sin desactivar los atajos del sistema."""
        if not self.hyprland_file.exists():
            return
        try:
            txt = self.hyprland_file.read_text(encoding="utf-8")
            txt = re.sub(r"^\s*omarchy_default_bindings\s*=\s*(true|false)\s*\n?", "", txt, flags=re.M)
            txt = re.sub(r"^\s*omarchy_preinstalled_bindings\s*=\s*(true|false)\s*\n?", "", txt, flags=re.M)

            if 'require("hyprland-gui")' not in txt:
                txt += '\n-- HyprMod & Meca managed settings\nrequire("hyprland-gui")\n'

            self.hyprland_file.write_text(txt, encoding="utf-8")
        except Exception:
            pass

    def save_gui_settings(self, settings: Dict[str, Any], apply_live: bool = True) -> bool:
        """Escribe todos los ajustes de Hyprland en ~/.config/hypr/hyprland-gui.lua y actualiza shell.json."""
        b = self._b

        # Guardar metadatos de opciones compuestas para recarga exacta
        meta_keys = {
            "animation_preset": settings.get("animation_preset", "omarchy"),
            "anim_windows": settings.get("anim_windows", "popin 87%"),
            "anim_windows_speed": float(settings.get("anim_windows_speed", 3.8)),
            "anim_fade_enabled": bool(settings.get("anim_fade_enabled", True)),
            "anim_layers": settings.get("anim_layers", "fade"),
            "anim_workspaces_enabled": bool(settings.get("anim_workspaces_enabled", False)),
            "anim_workspaces": settings.get("anim_workspaces", "slide"),
            "anim_special": settings.get("anim_special", "slidevert"),
            "cursor_theme": str(settings.get("cursor_theme", "default")),
            "cursor_size": int(settings.get("cursor_size", 24)),
            "kb_model": str(settings.get("kb_model", "pc105")),
            "kb_grp_toggle": str(settings.get("kb_grp_toggle", "Alt Izq + Alt Der")),
            "workspace_swipe": bool(settings.get("workspace_swipe", False)),
            "workspace_count": int(settings.get("workspace_count", 5)),
            "workspace_layout": str(settings.get("workspace_layout", "dwindle")),
            "single_window_aspect": str(settings.get("single_window_aspect", "0 0")),
            "rules_terminal_scroll": float(settings.get("rules_terminal_scroll", 1.5)),
            "rules_browser_opaque": bool(settings.get("rules_browser_opaque", True)),
            "rules_media_opaque": bool(settings.get("rules_media_opaque", True)),
            "rules_pavucontrol_float": bool(settings.get("rules_pavucontrol_float", True)),
            "rules_calculator_float": bool(settings.get("rules_calculator_float", True)),
            "rules_pip_float": bool(settings.get("rules_pip_float", True)),
            "rules_steam_float": bool(settings.get("rules_steam_float", True)),
            "rules_localsend_float": bool(settings.get("rules_localsend_float", True)),
        }
        meta_json = json.dumps(meta_keys, ensure_ascii=False)

        # Calcular curvas y velocidades según preset de animación
        preset = str(settings.get("animation_preset", "omarchy"))
        win_spd = float(settings.get("anim_windows_speed", 3.8))
        if preset == "snappy":
            spd_mult = 0.65
        elif preset == "minimal":
            spd_mult = 0.40
        elif preset == "smooth":
            spd_mult = 1.15
        else:
            spd_mult = 1.0

        w_style = str(settings.get("anim_windows", "popin 87%"))
        l_style = str(settings.get("anim_layers", "fade"))
        ws_en = b(settings.get("anim_workspaces_enabled", False))
        ws_style = str(settings.get("anim_workspaces", "slide"))
        sp_style = str(settings.get("anim_special", "slidevert"))
        fade_en = b(settings.get("anim_fade_enabled", True))
        c_theme = str(settings.get("cursor_theme", "default")).strip() or "default"
        c_size = int(settings.get("cursor_size", 24))

        # Aspect ratio de ventana única
        aspect_parts = str(settings.get("single_window_aspect", "0 0")).split()
        ax = int(aspect_parts[0]) if len(aspect_parts) >= 2 and aspect_parts[0].isdigit() else 0
        ay = int(aspect_parts[1]) if len(aspect_parts) >= 2 and aspect_parts[1].isdigit() else 0

        # Opciones de teclado (Compose + Cambio de distribución)
        compose_opt = "compose:ralt" if settings.get("compose_key", "ralt") == "ralt" else "compose:caps"
        grp_label = str(settings.get("kb_grp_toggle", "Alt Izq + Alt Der"))
        grp_map = {
            "Alt Izq + Alt Der": "grp:alts_toggle",
            "Alt + Shift": "grp:alt_shift_toggle",
            "Super + Espacio": "grp:win_space_toggle",
            "Ctrl + Shift": "grp:ctrl_shift_toggle",
            "Ninguno": "",
        }
        grp_opt = grp_map.get(grp_label, "grp:alts_toggle")
        opt_parts = [compose_opt, "shift:both_capslock_cancel"]
        if grp_opt:
            opt_parts.append(grp_opt)
        kb_options_str = ",".join(opt_parts)

        # Reglas de espacios de trabajo persistentes
        ws_count = max(1, min(10, int(settings.get("workspace_count", 5))))
        ws_layout = str(settings.get("workspace_layout", "dwindle"))
        ws_rules_lines = []
        for i in range(1, ws_count + 1):
            ws_rules_lines.append(f'hl.workspace_rule({{ workspace = "{i}", persistent = true, layout = "{ws_layout}" }})')
        ws_rules_block = "\n".join(ws_rules_lines)

        # Gesto de 3 dedos para cambiar de espacio de trabajo
        gesture_block = (
            '\nhl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })\n'
            if settings.get("workspace_swipe", False)
            else ""
        )

        # Reglas de ventana configurables
        term_scroll = float(settings.get("rules_terminal_scroll", 1.5))
        win_rules: List[str] = [
            "-- Regla de ventana flotante vertical (más altura que anchura) para Meca HyprConfig",
            'if o and o.window then',
            '  o.window("(org.omarchy.meca|meca-hyprconfig)", { tag = "-floating-window", float = true, center = true, size = { 680, 960 } })',
            '  o.window({ title = "^MECA HyprConfig$" }, { tag = "-floating-window", float = true, center = true, size = { 680, 960 } })',
            f'  o.window("(Alacritty|kitty|foot)", {{ scroll_touchpad = {term_scroll:.2f} }})',
        ]
        if settings.get("rules_pavucontrol_float", True):
            win_rules.append('  o.window("(org.pulseaudio.pavucontrol|pavucontrol)", { float = true, center = true, size = { 760, 520 } })')
        if settings.get("rules_calculator_float", True):
            win_rules.append('  o.window("(org.gnome.Calculator|qalculate-gtk|omacalc)", { float = true, center = true })')
        if settings.get("rules_browser_opaque", True):
            win_rules.append('  o.window({ tag = "chromium-based-browser" }, { tag = "-default-opacity", tile = true, opacity = "1.0 0.985" })')
            win_rules.append('  o.window({ tag = "firefox-based-browser" }, { tag = "-default-opacity", opacity = "1.0 0.985" })')
        if settings.get("rules_media_opaque", True):
            win_rules.append('  o.window("^(zoom|vlc|mpv|org.kde.kdenlive|com.obsproject.Studio|imv)$", { tag = "-default-opacity", opacity = "1 1" })')
        if settings.get("rules_pip_float", True):
            win_rules.append('  o.window({ title = "(Picture.?in.?[Pp]icture)" }, { tag = "+pip", float = true, pin = true, size = { 600, 338 }, keep_aspect_ratio = true })')
        if settings.get("rules_steam_float", True):
            win_rules.append('  o.window({ class = "steam", title = "Steam" }, { float = true, center = true, size = { 1100, 700 } })')
        if settings.get("rules_localsend_float", True):
            win_rules.append('  o.window("localsend", { float = true, center = true, size = { 1100, 700 } })')
        win_rules.append("end")
        win_rules_block = "\n".join(win_rules)

        lua_content = f"""-- Generado automáticamente por Meca HyprConfig (MECA)
-- MECA_META: {meta_json}

hl.env("XCURSOR_THEME", "{c_theme}")
hl.env("HYPRCURSOR_THEME", "{c_theme}")
hl.env("XCURSOR_SIZE", "{c_size}")
hl.env("HYPRCURSOR_SIZE", "{c_size}")

hl.config({{
  general = {{
    gaps_in = {int(settings.get('gaps_in', 5))},
    gaps_out = {int(settings.get('gaps_out', 10))},
    border_size = {int(settings.get('border_size', 2))},
    resize_on_border = {b(settings.get('resize_on_border', False))},
    extend_border_grab_area = {int(settings.get('extend_border_grab_area', 15))},
    hover_icon_on_border = {b(settings.get('hover_icon_on_border', True))},
    allow_tearing = {b(settings.get('allow_tearing', False))},
    no_focus_fallback = {b(settings.get('no_focus_fallback', False))},
    layout = "{settings.get('layout', 'dwindle')}",
    snap = {{
      enabled = {b(settings.get('snap_enabled', False))},
      window_gap = {int(settings.get('snap_window_gap', 10))},
      monitor_gap = {int(settings.get('snap_monitor_gap', 10))},
      border_overlap = {b(settings.get('snap_border_overlap', False))},
    }},
  }},
  decoration = {{
    rounding = {int(settings.get('rounding', 0))},
    rounding_power = {float(settings.get('rounding_power', 2.0)):.2f},
    active_opacity = {float(settings.get('active_opacity', 1.0)):.2f},
    inactive_opacity = {float(settings.get('inactive_opacity', 1.0)):.2f},
    fullscreen_opacity = {float(settings.get('fullscreen_opacity', 1.0)):.2f},
    dim_inactive = {b(settings.get('dim_inactive', False))},
    dim_strength = {float(settings.get('dim_strength', 0.15)):.2f},
    dim_special = {float(settings.get('dim_special', 0.20)):.2f},
    blur = {{
      enabled = {b(settings.get('blur_enabled', False))},
      size = {int(settings.get('blur_size', 8))},
      passes = {int(settings.get('blur_passes', 1))},
      new_optimizations = {b(settings.get('blur_new_optimizations', True))},
      xray = {b(settings.get('blur_xray', False))},
      ignore_opacity = {b(settings.get('blur_ignore_opacity', True))},
      vibrancy = {float(settings.get('blur_vibrancy', 0.17)):.2f},
    }},
    shadow = {{
      enabled = {b(settings.get('shadow_enabled', False))},
      range = {int(settings.get('shadow_range', 4))},
      render_power = {int(settings.get('shadow_render_power', 3))},
      sharp = {b(settings.get('shadow_sharp', False))},
    }},
  }},
  animations = {{
    enabled = {b(settings.get('animations_enabled', True))},
    workspace_wraparound = {b(settings.get('animations_wraparound', False))},
  }},
  cursor = {{
    no_hardware_cursors = {b(settings.get('no_hw_cursors', True))},
    inactive_timeout = {int(settings.get('cursor_timeout', 0))},
    hide_on_key_press = {b(settings.get('cursor_hide_on_key', True))},
    hide_on_touch = {b(settings.get('cursor_hide_on_touch', True))},
    warp_on_change_workspace = {int(settings.get('cursor_warp_workspace', 1))},
    zoom_factor = {float(settings.get('cursor_zoom', 1.0)):.2f},
    zoom_rigid = {b(settings.get('cursor_zoom_rigid', False))},
  }},
  input = {{
    kb_layout = "{settings.get('kb_layout', 'es')}",
    kb_variant = "{settings.get('kb_variant', '')}",
    kb_model = "{settings.get('kb_model', 'pc105')}",
    kb_options = "{kb_options_str}",
    repeat_rate = {int(settings.get('repeat_rate', 40))},
    repeat_delay = {int(settings.get('repeat_delay', 250))},
    numlock_by_default = {b(settings.get('numlock', True))},
    follow_mouse = {int(settings.get('follow_mouse', 1))},
    mouse_refocus = {b(settings.get('mouse_refocus', True))},
    sensitivity = {float(settings.get('sensitivity', 0.0)):.2f},
    accel_profile = "{settings.get('accel_profile', 'flat')}",
    natural_scroll = {b(settings.get('mouse_natural_scroll', False))},
    left_handed = {b(settings.get('left_handed', False))},
    touchpad = {{
      natural_scroll = {b(settings.get('natural_scroll', False))},
      scroll_factor = {float(settings.get('touchpad_scroll_factor', 0.4)):.2f},
      clickfinger_behavior = {b(settings.get('clickfinger', True))},
      tap_to_click = {b(settings.get('tap_to_click', True))},
      disable_while_typing = {b(settings.get('disable_typing', True))},
      drag_3fg = {int(settings.get('touchpad_drag_3fg', 0))},
    }},
  }},
  binds = {{
    hide_special_on_workspace_change = {b(settings.get('binds_hide_special', True))},
    workspace_back_and_forth = {b(settings.get('binds_workspace_back_forth', False))},
    allow_workspace_cycles = {b(settings.get('binds_allow_cycles', False))},
  }},
  misc = {{
    focus_on_activate = {b(settings.get('misc_focus_on_activate', True))},
    key_press_enables_dpms = {b(settings.get('misc_dpms_key', True))},
    mouse_move_enables_dpms = {b(settings.get('misc_dpms_mouse', True))},
    on_focus_under_fullscreen = {int(settings.get('misc_focus_under_fs', 1))},
    animate_manual_resizes = {b(settings.get('misc_animate_resizes', False))},
    animate_mouse_windowdragging = {b(settings.get('misc_animate_dragging', False))},
    vrr = {int(settings.get('monitor_vrr', 0))},
  }},
  layout = {{
    single_window_aspect_ratio = {{ {ax}, {ay} }},
  }},
  dwindle = {{
    force_split = {int(settings.get('dwindle_force_split', 2))},
    preserve_split = {b(settings.get('dwindle_preserve_split', True))},
    smart_split = {b(settings.get('dwindle_smart_split', False))},
    smart_resizing = {b(settings.get('dwindle_smart_resizing', True))},
    default_split_ratio = {float(settings.get('dwindle_split_ratio', 1.0)):.2f},
  }},
  master = {{
    new_status = "{settings.get('master_new_status', 'master')}",
    mfact = {float(settings.get('master_mfact', 0.55)):.2f},
    orientation = "{settings.get('master_orientation', 'left')}",
  }},
  scrolling = {{
    column_width = {float(settings.get('scrolling_column_width', 0.49)):.2f},
  }},
  group = {{
    groupbar = {{
      enabled = {b(settings.get('groupbar_enabled', True))},
      font_size = {int(settings.get('groupbar_font_size', 12))},
      height = {int(settings.get('groupbar_height', 22))},
      gradients = {b(settings.get('groupbar_gradients', True))},
    }},
  }},
  xwayland = {{
    force_zero_scaling = {b(settings.get('xwayland_zero_scaling', True))},
  }},
}})

-- Animaciones detalladas gestionadas por Meca
hl.animation({{ leaf = "windows", enabled = true, speed = {win_spd * spd_mult:.2f}, bezier = "easeOutQuint", style = "{w_style}" }})
hl.animation({{ leaf = "windowsIn", enabled = true, speed = {(win_spd + 0.3) * spd_mult:.2f}, bezier = "easeOutQuint", style = "{w_style}" }})
hl.animation({{ leaf = "windowsOut", enabled = true, speed = {1.5 * spd_mult:.2f}, bezier = "linear", style = "{w_style}" }})
hl.animation({{ leaf = "fade", enabled = {fade_en}, speed = {3.0 * spd_mult:.2f}, bezier = "quick" }})
hl.animation({{ leaf = "layersIn", enabled = true, speed = {4.0 * spd_mult:.2f}, bezier = "easeOutQuint", style = "{l_style}" }})
hl.animation({{ leaf = "layersOut", enabled = true, speed = {1.5 * spd_mult:.2f}, bezier = "linear", style = "{l_style}" }})
hl.animation({{ leaf = "workspaces", enabled = {ws_en}, speed = {3.2 * spd_mult:.2f}, bezier = "easeOutQuint", style = "{ws_style}" }})
hl.animation({{ leaf = "specialWorkspace", enabled = true, speed = {3.0 * spd_mult:.2f}, bezier = "easeOutQuint", style = "{sp_style}" }})

{ws_rules_block}
{gesture_block}
{win_rules_block}
"""
        try:
            self.gui_file.write_text(lua_content, encoding="utf-8")
            self._update_hyprland_lua_binding_flags(settings)
            self.save_bar_settings(settings, reload_shell=apply_live)

            if apply_live:
                subprocess.run(
                    ["hyprctl", "setcursor", c_theme, str(c_size)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
                subprocess.run(
                    ["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", c_theme],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
                subprocess.run(
                    ["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", str(c_size)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
                HyprIPC.reload()

            return True
        except Exception:
            return False

    # =========================================================================
    # GESTIÓN DE AUTOSTART (~/.config/hypr/autostart.lua)
    # =========================================================================

    def list_installed_applications(self) -> List[Dict[str, str]]:
        """
        Escanea archivos .desktop del sistema y del usuario para ofrecer un buscador
        y selector desplegable de aplicaciones y servicios en la sección Autostart.
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

        builtin_services = [
            ("Hyprsunset (Filtro de luz nocturna)", "hyprsunset", "launch"),
            ("NetworkManager Applet (Bandeja de red)", "nm-applet --indicator", "launch"),
            ("Blueman Applet (Bandeja Bluetooth)", "blueman-applet", "launch"),
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
                exec_clean = re.sub(r"\s+%[fFuUdDnNickvm]", "", exec_raw).strip()
                exec_clean = re.sub(r'^"([^"]+)"$', r"\1", exec_clean).strip()
                if exec_clean.startswith("/usr/bin/") and " " not in exec_clean:
                    exec_clean = exec_clean[len("/usr/bin/") :]

                if not exec_clean or exec_clean in seen_cmds or "meca" in exec_clean:
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
        HyprIPC.set_keyword("input:kb_options", f"{compose_opt},shift:both_capslock_cancel")

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

    def save_monitor_config(
        self,
        monitor_name: str,
        resolution: str,
        hz: float,
        scale: float,
        x: int = 0,
        y: int = 0,
        transform: int = 0,
        gdk_scale: int = 1,
    ) -> bool:
        """Guarda y aplica la configuración de un monitor en monitors.lua usando la sintaxis nativa de Omarchy."""
        out_name = monitor_name or ""
        if resolution == "preferred":
            mode_str = "preferred"
        else:
            mode_str = f"{resolution}@{hz:.2f}" if resolution else "preferred"
        transform_part = f", transform = {int(transform)}" if int(transform) > 0 else ""
        lua_content = f"""-- See https://wiki.hypr.land/Configuring/Basics/Monitors/
-- Gestionado por Meca HyprConfig

local omarchy_gdk_scale = {int(gdk_scale)}
local omarchy_monitor_scale = {scale}

hl.env("GDK_SCALE", tostring(omarchy_gdk_scale))
hl.monitor({{ output = "{out_name}", mode = "{mode_str}", position = "{x}x{y}", scale = omarchy_monitor_scale{transform_part} }})
"""
        try:
            with open(self.monitors_file, "w", encoding="utf-8") as f:
                f.write(lua_content)

            if transform > 0:
                HyprIPC.set_keyword("monitor", f"{out_name},{mode_str},{x}x{y},{scale},transform,{int(transform)}")
            else:
                HyprIPC.set_keyword("monitor", f"{out_name},{mode_str},{x}x{y},{scale}")
            return True
        except Exception:
            return False
