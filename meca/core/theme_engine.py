"""
Módulo de Integración y Edición de Temas de Omarchy.
Detecta el tema activo, lee colors.toml, genera secuencias ANSI de color
y permite editar tanto el tema activo como el tema original.
"""

from __future__ import annotations
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Dict, Any, List, Optional


class ThemeEngine:
    def __init__(self):
        self.user_themes_dir = Path.home() / ".config" / "omarchy" / "themes"
        self.system_themes_dir = Path("/usr/share/omarchy/themes")
        self.current_theme_dir = Path.home() / ".config" / "omarchy" / "current" / "theme"
        self.state_theme_dir = Path.home() / ".local" / "state" / "omarchy" / "current" / "theme"
        self._current_theme_name: Optional[str] = None
        self._colors: Dict[str, str] = {}
        self._mode: str = "dark"
        self._icon_theme: str = "Adwaita"
        self.reload()

    def get_current_theme_name(self) -> str:
        """Obtiene el nombre del tema activo a través de omarchy."""
        state_name_file = Path.home() / ".local" / "state" / "omarchy" / "current" / "theme.name"
        if state_name_file.exists():
            try:
                name = state_name_file.read_text(encoding="utf-8").strip()
                if name:
                    return name
            except Exception:
                pass

        try:
            res = subprocess.run(
                ["omarchy", "theme", "current"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass

        if self.current_theme_dir.exists() and self.current_theme_dir.is_symlink():
            target = os.readlink(self.current_theme_dir)
            return Path(target).name

        return "rose-pine"

    def normalize_theme_slug(self, theme_name: str) -> str:
        """Normaliza el nombre del tema al formato de carpeta de Omarchy."""
        return theme_name.strip().lower().replace(" ", "-")

    def list_available_themes(self) -> List[str]:
        """Lista todos los temas disponibles en el sistema y usuario."""
        themes = set()
        for d in [self.user_themes_dir, self.system_themes_dir]:
            if d.exists() and d.is_dir():
                for item in d.iterdir():
                    if item.is_dir() and ((item / "colors.toml").exists() or (item / "alacritty.toml").exists()):
                        themes.add(item.name)
        return sorted(list(themes))

    def _find_theme_dirs(self, theme_name: str) -> List[Path]:
        """Devuelve todas las rutas existentes asociadas a este tema (usuario, sistema, actual)."""
        slug = self.normalize_theme_slug(theme_name)
        candidates = [
            self.user_themes_dir / slug,
            self.user_themes_dir / theme_name,
            self.system_themes_dir / slug,
            self.system_themes_dir / theme_name,
        ]
        found: List[Path] = []
        for c in candidates:
            if c.exists() and c.is_dir() and c not in found:
                found.append(c)

        # Búsqueda insensible a mayúsculas/guiones si no se halló coincidencia directa
        if not found:
            cleaned_target = re.sub(r"[\s\-_]+", "", theme_name.lower())
            for base in [self.user_themes_dir, self.system_themes_dir]:
                if base.exists():
                    for item in base.iterdir():
                        if item.is_dir():
                            cleaned = re.sub(r"[\s\-_]+", "", item.name.lower())
                            if cleaned == cleaned_target and item not in found:
                                found.append(item)
        return found

    def _find_theme_dir(self, theme_name: str) -> Optional[Path]:
        """Localiza el directorio principal del tema, priorizando usuario y current."""
        dirs = self._find_theme_dirs(theme_name)
        if dirs:
            return dirs[0]
        if self.current_theme_dir.exists():
            return self.current_theme_dir
        return None

    def reload(self) -> None:
        """Recarga la configuración del tema actual."""
        self._current_theme_name = self.get_current_theme_name()
        theme_dir = self._find_theme_dir(self._current_theme_name)

        default_colors = {
            "accent": "#E31B23",
            "selection": "#45475a",
            "background": "#08080B",
            "foreground": "#d8d8d8",
            "muted": "#585b70",
            "red": "#E31B23",
            "green": "#2DB872",
            "yellow": "#E5A83B",
            "blue": "#5A7DA8",
            "cyan": "#45A0B5",
            "bright_foreground": "#ffffff",
        }
        self._mode = "dark"
        self._icon_theme = "Adwaita"

        # Leer desde el directorio del tema o desde current/theme
        search_dirs = []
        if theme_dir:
            search_dirs.append(theme_dir)
        if self.current_theme_dir.exists() and self.current_theme_dir not in search_dirs:
            search_dirs.append(self.current_theme_dir)

        for d in search_dirs:
            colors_file = d / "colors.toml"
            if colors_file.exists():
                try:
                    with open(colors_file, "rb") as f:
                        data = tomllib.load(f)
                        if "mode" in data and isinstance(data["mode"], str):
                            self._mode = data["mode"]
                        for k, v in data.items():
                            if isinstance(v, str) and v.startswith("#"):
                                default_colors[k] = v
                    break
                except Exception:
                    pass

        for d in search_dirs:
            icons_file = d / "icons.theme"
            if icons_file.exists():
                try:
                    icon_txt = icons_file.read_text(encoding="utf-8").strip()
                    if icon_txt:
                        self._icon_theme = icon_txt
                    break
                except Exception:
                    pass

        # En temas claros donde bright_foreground no esté en colors.toml, asegurar contraste
        if self._mode == "light" and "bright_foreground" not in (data if "data" in locals() else {}):
            default_colors["bright_foreground"] = default_colors.get("foreground", "#000000")

        self._colors = default_colors
        self.update_derived_colors()

    @classmethod
    def blend_hex(cls, hex_base: str, hex_tint: str, ratio: float) -> str:
        """Mezcla dos colores hexadecimales con proporción 'ratio' (0.0 = base, 1.0 = tint) para destellos suaves."""
        ratio = max(0.0, min(1.0, ratio))
        r1, g1, b1 = cls.hex_to_rgb(hex_base)
        r2, g2, b2 = cls.hex_to_rgb(hex_tint)
        r = int(r1 * (1.0 - ratio) + r2 * ratio)
        g = int(g1 * (1.0 - ratio) + g2 * ratio)
        b = int(b1 * (1.0 - ratio) + b2 * ratio)
        return f"#{r:02x}{g:02x}{b:02x}"

    def update_derived_colors(self) -> None:
        """
        Calcula colores derivados suaves (soft_hover, soft_selection, soft_muted)
        para evitar que el destello al pasar el cursor ilumine demasiado en modo oscuro.
        """
        bg = self._colors.get("background", "#08080B")
        accent = self._colors.get("accent", "#E31B23")
        sel = self._colors.get("selection", "#45475a")
        muted = self._colors.get("muted", "#585b70")

        if self._mode == "light":
            self._colors["soft_hover"] = self.blend_hex(bg, accent, 0.16)
            self._colors["soft_selection"] = self.blend_hex(bg, sel, 0.45)
            self._colors["soft_muted"] = self.blend_hex(bg, muted, 0.22)
        else:
            # En modo oscuro, mezclamos solo un 22% del color de acento sobre el fondo oscuro
            # para lograr un destello suave que mantiene legibilidad perfecta del texto claro.
            self._colors["soft_hover"] = self.blend_hex(bg, accent, 0.22)
            sr, sg, sb = self.hex_to_rgb(sel)
            sel_lum = 0.299 * sr + 0.587 * sg + 0.114 * sb
            sel_ratio = 0.24 if sel_lum > 85 else 0.65
            self._colors["soft_selection"] = self.blend_hex(bg, sel, sel_ratio)
            self._colors["soft_muted"] = self.blend_hex(bg, muted, 0.38)

    @property
    def current_theme(self) -> str:
        return self._current_theme_name or "rose-pine"

    @property
    def colors(self) -> Dict[str, str]:
        return self._colors

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def icon_theme(self) -> str:
        return self._icon_theme

    @staticmethod
    def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
        hex_clean = hex_str.lstrip("#")
        if len(hex_clean) == 3:
            hex_clean = "".join(c * 2 for c in hex_clean)
        if len(hex_clean) >= 6:
            try:
                return (
                    int(hex_clean[0:2], 16),
                    int(hex_clean[2:4], 16),
                    int(hex_clean[4:6], 16),
                )
            except ValueError:
                pass
        return (255, 255, 255)

    def fg(self, color_key: str, text: str) -> str:
        """Devuelve el texto coloreado con truecolor ANSI (primer plano)."""
        hex_val = self._colors.get(color_key, "#ffffff")
        r, g, b = self.hex_to_rgb(hex_val)
        return f"\033[38;2;{r};{g};{b}m{text}\033[0m"

    def bg(self, color_key: str, text: str) -> str:
        """Devuelve el texto coloreado con truecolor ANSI (fondo)."""
        hex_val = self._colors.get(color_key, "#000000")
        r, g, b = self.hex_to_rgb(hex_val)
        return f"\033[48;2;{r};{g};{b}m{text}\033[0m"

    def style(self, fg_key: str, bg_key: Optional[str], text: str, bold: bool = False) -> str:
        """Aplica estilos combinados de primer plano, fondo y negrita."""
        prefix = "\033[1m" if bold else ""
        fg_hex = self._colors.get(fg_key, "#ffffff")
        fr, fg_val, fb = self.hex_to_rgb(fg_hex)
        prefix += f"\033[38;2;{fr};{fg_val};{fb}m"

        if bg_key:
            bg_hex = self._colors.get(bg_key, "#000000")
            br, bg_val, bb = self.hex_to_rgb(bg_hex)
            prefix += f"\033[48;2;{br};{bg_val};{bb}m"

        return f"{prefix}{text}\033[0m"

    def list_user_themes(self) -> List[str]:
        """Lista los temas creados o personalizados en ~/.config/omarchy/themes."""
        themes: List[str] = []
        if self.user_themes_dir.exists() and self.user_themes_dir.is_dir():
            for item in sorted(self.user_themes_dir.iterdir(), key=lambda p: p.name.lower()):
                if item.is_dir() and ((item / "colors.toml").exists() or (item / "alacritty.toml").exists()):
                    themes.append(item.name)
        return themes

    def get_theme_info(self, theme_name: str) -> Dict[str, Any]:
        """Obtiene la información (modo, colores, iconos, origen) de cualquier tema Omarchy."""
        slug = self.normalize_theme_slug(theme_name)
        u_dir = self.user_themes_dir / slug
        s_dir = self.system_themes_dir / slug
        is_user = u_dir.exists()
        is_system = s_dir.exists()

        info: Dict[str, Any] = {
            "name": slug,
            "mode": "dark",
            "accent": "#7aa2f7",
            "background": "#1a1b26",
            "foreground": "#a9b1d6",
            "selection": "#292e42",
            "icons": "Adwaita",
            "is_user": is_user,
            "is_system": is_system,
        }
        target_dir = u_dir if is_user else (s_dir if is_system else self._find_theme_dir(theme_name))
        if target_dir and target_dir.exists():
            c_file = target_dir / "colors.toml"
            if c_file.exists():
                try:
                    with open(c_file, "rb") as f:
                        data = tomllib.load(f)
                        for k in ("mode", "accent", "background", "foreground", "selection"):
                            if k in data and isinstance(data[k], str):
                                info[k] = data[k]
                except Exception:
                    pass
            i_file = target_dir / "icons.theme"
            if i_file.exists():
                try:
                    ic = i_file.read_text(encoding="utf-8").strip()
                    if ic:
                        info["icons"] = ic
                except Exception:
                    pass
        return info

    def create_theme(
        self,
        new_name: str,
        base_theme: Optional[str] = None,
        mode: str = "dark",
        custom_colors: Optional[Dict[str, str]] = None,
        activate: bool = True,
    ) -> tuple[bool, str]:
        """
        Crea un nuevo tema Omarchy en ~/.config/omarchy/themes/<slug> clonando la estructura
        y fondos del tema base indicado y aplicando el modo y paleta personalizados.
        """
        slug = re.sub(r"[^a-z0-9\-_]", "", self.normalize_theme_slug(new_name))
        if not slug:
            return False, "Nombre de tema invalido. Usa letras, numeros o guiones."

        dest_dir = self.user_themes_dir / slug
        if dest_dir.exists():
            return False, f"El tema '{slug}' ya existe en ~/.config/omarchy/themes."

        base_slug = self.normalize_theme_slug(base_theme or self.current_theme)
        base_dir = self._find_theme_dir(base_slug)
        if not base_dir or not base_dir.exists():
            base_dir = self.system_themes_dir / "tokyo-night"

        try:
            self.user_themes_dir.mkdir(parents=True, exist_ok=True)
            if base_dir and base_dir.exists():
                shutil.copytree(base_dir, dest_dir, symlinks=False)
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
                (dest_dir / "backgrounds").mkdir(exist_ok=True)
                (dest_dir / "icons.theme").write_text("Yaru-blue\n", encoding="utf-8")
                (dest_dir / "colors.toml").write_text(
                    'mode = "dark"\naccent = "#7aa2f7"\nselection = "#292e42"\nmuted = "#414868"\n'
                    'background = "#1a1b26"\nforeground = "#a9b1d6"\nbright_foreground = "#c0caf5"\n',
                    encoding="utf-8",
                )

            updates = {"mode": mode}
            if custom_colors:
                updates.update(custom_colors)

            self.save_theme_edits(
                theme_name=slug,
                updates=updates,
                refresh_live=False,
            )

            # Si /usr/share/omarchy/themes existe, intentar copiar también al directorio del sistema
            sys_dest = self.system_themes_dir / slug
            if self.system_themes_dir.exists() and not sys_dest.exists():
                if os.access(self.system_themes_dir, os.W_OK):
                    try:
                        shutil.copytree(dest_dir, sys_dest, symlinks=False)
                    except Exception:
                        pass
                else:
                    try:
                        subprocess.run(
                            ["sudo", "-n", "cp", "-r", str(dest_dir), str(sys_dest)],
                            capture_output=True,
                            timeout=3,
                        )
                    except Exception:
                        pass

            if activate:
                self.set_theme(slug)
            return True, f"✓ Tema Omarchy '{slug}' creado a partir de '{base_slug}'."
        except Exception as e:
            return False, f"Error al crear el tema: {e}"

    def delete_user_theme(self, theme_name: str) -> tuple[bool, str]:
        """Elimina un tema personalizado de ~/.config/omarchy/themes/<slug>."""
        slug = self.normalize_theme_slug(theme_name)
        u_dir = self.user_themes_dir / slug
        s_dir = self.system_themes_dir / slug

        if not u_dir.exists() and not u_dir.is_symlink():
            return False, f"El tema '{slug}' es un tema base del sistema y no tiene copia de usuario."

        try:
            was_active = (slug == self.normalize_theme_slug(self.current_theme))
            if u_dir.is_symlink() or u_dir.is_file():
                u_dir.unlink()
            else:
                shutil.rmtree(u_dir)

            if was_active:
                if s_dir.exists():
                    self.set_theme(slug)
                    return True, f"✓ Personalizacion de '{slug}' eliminada; restaurado tema original."
                else:
                    fallback = "tokyo-night" if (self.system_themes_dir / "tokyo-night").exists() else "catppuccin"
                    self.set_theme(fallback)
                    return True, f"✓ Tema '{slug}' eliminado. Tema cambiado a '{fallback}'."

            return True, f"✓ Tema de usuario '{slug}' eliminado correctamente."
        except Exception as e:
            return False, f"No se pudo eliminar '{slug}': {e}"

    def set_theme(self, theme_name: str) -> bool:
        """Aplica un tema utilizando omarchy-theme-set."""
        slug = self.normalize_theme_slug(theme_name)
        try:
            res = subprocess.run(
                ["omarchy-theme-set", slug],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode != 0:
                res = subprocess.run(
                    ["omarchy", "theme", "set", slug],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            if res.returncode == 0:
                self.reload()
                return True
        except Exception:
            pass
        return False

    def save_theme_edits(
        self,
        theme_name: Optional[str] = None,
        updates: Optional[Dict[str, str]] = None,
        icon_theme: Optional[str] = None,
        refresh_live: bool = True,
    ) -> bool:
        """
        Edita el tema Omarchy indicado (o el actual) modificando tanto la copia
        de usuario (~/.config/omarchy/themes/<tema>) como el tema original
        (/usr/share/omarchy/themes/<tema> si tiene permisos de escritura, y
        ~/.config/omarchy/current/theme) y refresca Omarchy.
        """
        target_name = theme_name or self.current_theme
        slug = self.normalize_theme_slug(target_name)
        sys_dir = self.system_themes_dir / slug
        user_dir = self.user_themes_dir / slug
        is_current = (slug == self.normalize_theme_slug(self.current_theme))

        try:
            # 1. Asegurar que la carpeta de usuario tenga todos los archivos originales del tema
            if user_dir.is_symlink():
                real_src = user_dir.resolve()
                user_dir.unlink()
                if real_src.exists() and real_src.is_dir():
                    shutil.copytree(real_src, user_dir, symlinks=False)

            user_dir.mkdir(parents=True, exist_ok=True)
            if sys_dir.exists() and sys_dir.is_dir():
                for entry in sys_dir.iterdir():
                    dest = user_dir / entry.name
                    if not dest.exists():
                        if entry.is_dir():
                            shutil.copytree(entry, dest, symlinks=False)
                        elif entry.is_file():
                            shutil.copy2(entry, dest)

            # Directorios donde se aplicará la edición (original del sistema, usuario y activo si coincide)
            target_dirs: List[Path] = [user_dir]
            if sys_dir.exists() and os.access(sys_dir, os.W_OK):
                target_dirs.append(sys_dir)
            if is_current:
                if self.current_theme_dir.exists() and self.current_theme_dir not in target_dirs:
                    target_dirs.append(self.current_theme_dir)
                if self.state_theme_dir.exists() and self.state_theme_dir not in target_dirs:
                    target_dirs.append(self.state_theme_dir)

            # 2. Actualizar colors.toml preservando comentarios y estructura
            if updates:
                base_colors_file = user_dir / "colors.toml"
                if not base_colors_file.exists() and sys_dir.exists() and (sys_dir / "colors.toml").exists():
                    shutil.copy2(sys_dir / "colors.toml", base_colors_file)

                if base_colors_file.exists():
                    content = base_colors_file.read_text(encoding="utf-8")
                else:
                    content = 'mode = "dark"\n'

                for k, val in updates.items():
                    if not val:
                        continue
                    pattern = re.compile(rf"^(\s*{re.escape(k)}\s*=\s*)\"[^\"]*\"", re.MULTILINE)
                    if pattern.search(content):
                        content = pattern.sub(rf'\g<1>"{val}"', content)
                    else:
                        content = content.rstrip() + f'\n{k} = "{val}"\n'

                for d in target_dirs:
                    c_file = d / "colors.toml"
                    try:
                        c_file.write_text(content, encoding="utf-8")
                    except Exception:
                        pass

                if sys_dir.exists() and (sys_dir / "colors.toml").exists() and not os.access(sys_dir / "colors.toml", os.W_OK):
                    try:
                        subprocess.run(
                            ["sudo", "-n", "cp", str(user_dir / "colors.toml"), str(sys_dir / "colors.toml")],
                            capture_output=True,
                            timeout=2,
                        )
                    except Exception:
                        pass

            # 3. Actualizar icons.theme si se especificó
            if icon_theme:
                for d in target_dirs:
                    i_file = d / "icons.theme"
                    try:
                        i_file.write_text(f"{icon_theme.strip()}\n", encoding="utf-8")
                    except Exception:
                        pass
                if sys_dir.exists() and not os.access(sys_dir, os.W_OK):
                    try:
                        subprocess.run(
                            ["sudo", "-n", "cp", str(user_dir / "icons.theme"), str(sys_dir / "icons.theme")],
                            capture_output=True,
                            timeout=2,
                        )
                    except Exception:
                        pass

            # 4. Refrescar el tema en Omarchy para regenerar plantillas y recargar colores
            if refresh_live and is_current:
                try:
                    subprocess.run(["omarchy-theme-refresh"], capture_output=True, timeout=10)
                except Exception:
                    pass
                self.reload()

            return True
        except Exception:
            return False
