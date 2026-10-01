"""
Punto de Entrada CLI para Meca HyprConfig.
Permite iniciar la interfaz interactiva TUI o ejecutar comandos directos de preparación.
"""

from __future__ import annotations
import sys
import argparse
from pathlib import Path

from meca import __version__
from meca.core.theme_engine import ThemeEngine
from meca.core.hypr_ipc import HyprIPC
from meca.core.config_sync import ConfigSync
from meca.core.lizarbe_manager import LizarbeManager
from meca.ui.tui import MecaTUI


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="meca",
        description="Meca HyprConfig — Panel TUI de configuración monolítica para Hyprland + Omarchy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  meca                  Inicia el panel interactivo TUI
  meca --fix-caps       Libera la tecla Bloq Mayús reasignando Compose a Alt Gr
  meca --apply-lizarbe  Aplica el tema Lizarbe y sus iconos
  meca --setup          Aplica todas las preparaciones para nuevos usuarios
  meca --status         Muestra el estado actual del entorno y módulos
        """
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--status", action="store_true", help="Muestra el estado de la configuración actual")
    parser.add_argument("--fix-caps", action="store_true", help="Corrige la tecla Bloq Mayús (Caps Lock)")
    parser.add_argument("--apply-lizarbe", action="store_true", help="Aplica el tema Lizarbe")
    parser.add_argument("--setup", action="store_true", help="Ejecuta la preparación completa para nuevos usuarios")
    return parser.parse_args()


def print_status() -> None:
    theme_engine = ThemeEngine()
    config_sync = ConfigSync()
    settings = config_sync.load_gui_settings()
    monitors = HyprIPC.get_monitors()

    print(f"\033[1;38;2;227;27;35mMECA HyprConfig v{__version__}\033[0m")
    print("=" * 45)
    print(f"• Hyprland Activo: {'✓ Sí' if HyprIPC.is_running() else '✗ No'}")
    print(f"• Versión Hyprland: {HyprIPC.get_version_info()}")
    print(f"• Tema Omarchy Activo: {theme_engine.current_theme}")
    print(f"• Monitores Detectados: {len(monitors)}")
    for m in monitors:
        print(f"    - {m.get('name')}: {m.get('width')}x{m.get('height')} @ {m.get('refreshRate', 60):.0f}Hz (Escala: {m.get('scale', 1.0)}x)")
    print(f"• Separación (Gaps): Out={settings.get('gaps_out')}px, In={settings.get('gaps_in')}px")
    print(f"• Bordes y Curvatura: Border={settings.get('border_size')}px, Rounding={settings.get('rounding')}px")
    print(f"• Tecla Bloq Mayús: {'✓ NORMAL (Compose en Alt Gr)' if settings.get('compose_key') == 'ralt' else 'Modo Omarchy (Bloq Mayús = Compose)'}")
    print(f"• Tema Lizarbe: {'✓ Instalado' if LizarbeManager.is_lizarbe_installed() else '✗ No detectado'}")
    print(f"• Logo Fastfetch: {'✓ Configurado' if LizarbeManager.is_fastfetch_lizarbe_configured() else '✗ Estándar'}")
    print("=" * 45)


def main() -> None:
    args = parse_args()

    if args.status:
        print_status()
        return

    if args.fix_caps:
        sync = ConfigSync()
        sync.fix_caps_lock(use_ralt=True)
        print("\033[32m✓ Tecla Bloq Mayús liberada con éxito. La tecla Compose ahora es Alt Gr (Alt Derecha).\033[0m")
        return

    if args.apply_lizarbe:
        print("Aplicando tema Lizarbe...")
        if LizarbeManager.apply_lizarbe_theme("lizarbe"):
            print("\033[32m✓ Tema Lizarbe aplicado correctamente.\033[0m")
        else:
            print("\033[31mError al aplicar el tema Lizarbe.\033[0m")
        return

    if args.setup:
        print("\033[1;38;2;227;27;35mIniciando Preparación Completa de Meca para Nuevos Usuarios...\033[0m")
        sync = ConfigSync()
        sync.fix_caps_lock(use_ralt=True)
        print("1/4 ✓ Tecla Bloq Mayús configurada (Alt Gr = Compose).")
        
        LizarbeManager.ensure_fastfetch_logo()
        print("2/4 ✓ Logo de Lizarbe configurado en Fastfetch.")
        
        # Instalar hook
        tui = MecaTUI()
        tui.install_update_hook()
        print("3/4 ✓ Hook para omarchy update registrado.")

        LizarbeManager.apply_lizarbe_theme("lizarbe")
        print("4/4 ✓ Tema Lizarbe activado en Omarchy.")
        print("\033[32m¡Preparación completada con éxito!\033[0m")
        return

    # Iniciar la interfaz TUI por defecto con pantalla de carga animada
    from meca.ui.loader import StartupLoader

    loader = StartupLoader()
    loader.start()
    try:
        app = MecaTUI(was_tiled=loader.was_tiled)
        loader.stop()
        app.run()
    except KeyboardInterrupt:
        loader.cleanup()
        sys.exit(0)
    except Exception:
        loader.cleanup()
        raise


if __name__ == "__main__":
    main()
