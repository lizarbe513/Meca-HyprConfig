"""
Pantalla de carga inicial (Splash Loader) para Meca HyprConfig.
Muestra una señal de carga elegante con 3 puntitos animados mientras
la aplicación inicializa sus módulos, temas y configuración en segundo plano.
"""

from __future__ import annotations
import os
import sys
import time
import shutil
import threading
from pathlib import Path
from typing import Optional, Tuple

from meca.core.hypr_ipc import HyprIPC


class StartupLoader:
    """
    Renderiza una pantalla de carga ligera y centrada con animación de 3 puntitos.
    Se ejecuta en un hilo secundario durante la inicialización de MecaTUI.
    """

    def __init__(self, title: str = "MECA HyprConfig"):
        self.title = title
        self.was_tiled: Optional[bool] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._start_time: float = 0.0
        self._is_active: bool = False
        self._accent_rgb, self._muted_rgb = self._detect_theme_colors()

    @staticmethod
    def _hex_to_rgb(hex_code: str, fallback: Tuple[int, int, int]) -> Tuple[int, int, int]:
        clean = hex_code.strip().lstrip("#")
        if len(clean) == 6:
            try:
                return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)
            except ValueError:
                pass
        return fallback

    def _detect_theme_colors(self) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
        """Detecta rápidamente los colores de acento y tenue de Omarchy sin sobrecargar el inicio."""
        accent = (227, 27, 35)  # #E31B23 (Rojo Meca por defecto)
        muted = (130, 130, 140)

        # Buscar colors.toml en las rutas de estado o configuración de Omarchy
        paths = [
            Path.home() / ".local" / "state" / "omarchy" / "current" / "theme" / "colors.toml",
            Path.home() / ".config" / "omarchy" / "current" / "theme" / "colors.toml",
        ]
        for p in paths:
            if p.exists():
                try:
                    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                        line = line.strip()
                        if line.startswith("accent") and "=" in line:
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            accent = self._hex_to_rgb(val, accent)
                        elif line.startswith("muted") and "=" in line:
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            muted = self._hex_to_rgb(val, muted)
                    break
                except Exception:
                    pass

        return accent, muted

    def _render_frame(self, frame_idx: int) -> None:
        """Dibuja un frame con el título y los 3 puntitos animados centrados."""
        cols, rows = shutil.get_terminal_size((80, 24))

        ar, ag, ab = self._accent_rgb
        mr, mg, mb = self._muted_rgb

        accent_ansi = f"\033[1;38;2;{ar};{ag};{ab}m"
        muted_ansi = f"\033[38;2;{mr};{mg};{mb}m"
        reset_ansi = "\033[0m"

        # 3 puntitos con ciclo suave (onda izquierda a derecha)
        # Frame 0: ● ○ ○
        # Frame 1: ○ ● ○
        # Frame 2: ○ ○ ●
        active_dot = frame_idx % 3
        dots_parts = []
        for i in range(3):
            if i == active_dot:
                dots_parts.append(f"{accent_ansi}●{reset_ansi}")
            else:
                dots_parts.append(f"{muted_ansi}○{reset_ansi}")
        dots_str = " ".join(dots_parts)

        # Cadenas para pantalla: sólo el símbolo de carga (3 puntitos animados) sin texto "Cargando"
        title_styled = f"{accent_ansi}󰏘  {self.title}{reset_ansi}"
        dots_styled = dots_str

        # Longitudes visuales limpias para calcular centrado
        title_visual_len = len(f"󰏘  {self.title}")
        dots_visual_len = 5  # "● ○ ○"

        center_y = max(2, (rows // 2) - 1)
        title_x = max(1, (cols - title_visual_len) // 2)
        dots_x = max(1, (cols - dots_visual_len) // 2)

        buf = [
            f"\033[{center_y};{title_x}H\033[K{title_styled}",
            f"\033[{center_y + 2};{dots_x}H\033[K{dots_styled}",
        ]

        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    def _worker(self) -> None:
        """Bucle del hilo de animación."""
        frame = 0
        while not self._stop_event.is_set():
            self._render_frame(frame)
            frame += 1
            # 140ms por frame para un ciclo suave y natural
            time.sleep(0.14)

    def start(self) -> None:
        """Inicia la pantalla de carga si estamos en una terminal TTY."""
        if not sys.stdout.isatty():
            return

        # Ajustar geometría de ventana de inmediato a vertical flotante
        self.was_tiled = HyprIPC.ensure_floating_centered(width=680, height=960)

        # Establecer título de ventana
        sys.stdout.write(f"\033]0;{self.title}\007\033]2;{self.title}\007")

        # Cambiar a alternate buffer, ocultar cursor y limpiar pantalla
        sys.stdout.write("\033[?1049h\033[?25l\033[2J")
        sys.stdout.flush()

        self._is_active = True
        self._start_time = time.time()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="StartupLoaderThread")
        self._thread.start()

    def stop(self, min_duration: float = 0.55) -> None:
        """Detiene el hilo asegurando un mínimo de tiempo visible para la animación."""
        if not self._is_active or not self._thread:
            return

        elapsed = time.time() - self._start_time
        if elapsed < min_duration:
            time.sleep(min_duration - elapsed)

        self._stop_event.set()
        self._thread.join(timeout=0.6)
        self._is_active = False

    def cleanup(self) -> None:
        """Restaura la terminal en caso de cancelación abrupta o error antes de iniciar la TUI."""
        if not self._is_active:
            return
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.3)
        # Restaurar cursor y salir de alternate buffer
        sys.stdout.write("\033[?25h\033[?1049l\033[0m")
        sys.stdout.flush()
        if self.was_tiled:
            HyprIPC.restore_tiled()
        self._is_active = False
