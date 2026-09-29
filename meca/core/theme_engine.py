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
            "icon_theme": "Adwaita",
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
                        info["icon_theme"] = ic
                except Exception:
                    pass
        return info

    def get_theme_full_spec(self, theme_name: str) -> Dict[str, Any]:
        """
        Analiza el directorio de un tema Omarchy integrado o de usuario y devuelve todos sus
        aspectos configurables: modo, color de acento, bordes de ventana enfocada/inactiva,
        fondo de widgets, tema de iconos, fondos de pantalla, preview, colores de terminal y extras.
        """
        slug = self.normalize_theme_slug(theme_name)
        t_dir = self._find_theme_dir(slug) or (self.system_themes_dir / "tokyo-night")

        spec: Dict[str, Any] = {
            "name": f"{slug}-custom",
            "base_theme": slug,
            "mode": "dark",
            "accent": "#7aa2f7",
            "active_border": "#7aa2f7",
            "inactive_border": "#414868",
            "selection": "#292e42",
            "muted": "#414868",
            "widget_bg": "#1a1b26",
            "widget_fg": "#a9b1d6",
            "widget_border": "#7aa2f7",
            "widget_alpha": 0.95,
            "icons": "Yaru-blue",
            "wallpapers_source": f"tema:{slug}",
            "custom_wallpaper": "ninguno",
            "preview_source": f"tema:{slug}",
            # Terminal colors
            "background": "#1a1b26",
            "dark_background": "#13141c",
            "darker_background": "#0e0e14",
            "lighter_background": "#24283b",
            "foreground": "#a9b1d6",
            "dark_foreground": "#565f89",
            "light_foreground": "#b4bee6",
            "bright_foreground": "#c0caf5",
            "red": "#f7768e",
            "yellow": "#e0af68",
            "orange": "#eb927b",
            "green": "#9ece6a",
            "cyan": "#449dab",
            "blue": "#7aa2f7",
            "magenta": "#ad8ee6",
            "brown": "#75493d",
            "bright_red": "#ff7a93",
            "bright_yellow": "#ff9e64",
            "bright_green": "#b9f27c",
            "bright_cyan": "#0db9d7",
            "bright_blue": "#7da6ff",
            "bright_magenta": "#bb9af7",
            # Extras
            "neovim_scheme": "tokyonight-night",
            "keyboard_rgb": "7aa2f7",
            "activate_on_create": True,
        }

        if not t_dir or not t_dir.exists():
            return spec

        # 1. Leer colors.toml
        c_file = t_dir / "colors.toml"
        if c_file.exists():
            try:
                with open(c_file, "rb") as f:
                    data = tomllib.load(f)
                for k in (
                    "mode", "accent", "selection", "muted",
                    "background", "dark_background", "darker_background", "lighter_background",
                    "foreground", "dark_foreground", "light_foreground", "bright_foreground",
                    "red", "yellow", "orange", "green", "cyan", "blue", "magenta", "brown",
                    "bright_red", "bright_yellow", "bright_green", "bright_cyan", "bright_blue", "bright_magenta",
                ):
                    if k in data and isinstance(data[k], str):
                        spec[k] = data[k]
                # Bordes si están definidos en colors.toml
                if "hyprland_active_border" in data and isinstance(data["hyprland_active_border"], str):
                    val = data["hyprland_active_border"]
                    m_hex = re.search(r"#([0-9a-fA-F]{6})", val)
                    m_rgb = re.search(r"rgba?\(([0-9a-fA-F]{6})", val)
                    if m_hex:
                        spec["active_border"] = f"#{m_hex.group(1)}"
                    elif m_rgb:
                        spec["active_border"] = f"#{m_rgb.group(1)}"
                elif "active_border_color" in data and isinstance(data["active_border_color"], str):
                    spec["active_border"] = data["active_border_color"]
                else:
                    spec["active_border"] = spec["accent"]

                if "hyprland_inactive_border" in data and isinstance(data["hyprland_inactive_border"], str):
                    val = data["hyprland_inactive_border"]
                    m_hex = re.search(r"#([0-9a-fA-F]{6})", val)
                    m_rgb = re.search(r"rgba?\(([0-9a-fA-F]{6})", val)
                    if m_hex:
                        spec["inactive_border"] = f"#{m_hex.group(1)}"
                    elif m_rgb:
                        spec["inactive_border"] = f"#{m_rgb.group(1)}"
                else:
                    spec["inactive_border"] = spec["muted"]
            except Exception:
                pass

        # 2. Leer hyprland.lua si existe para bordes específicos
        h_file = t_dir / "hyprland.lua"
        if h_file.exists():
            try:
                htxt = h_file.read_text(encoding="utf-8")
                m_act = re.search(r"active_border_color\s*=\s*.*?([0-9a-fA-F]{6})", htxt)
                if m_act:
                    spec["active_border"] = f"#{m_act.group(1)}"
                m_inact = re.search(r"inactive_border_color\s*=\s*.*?([0-9a-fA-F]{6})", htxt)
                if m_inact:
                    spec["inactive_border"] = f"#{m_inact.group(1)}"
            except Exception:
                pass

        # Inicializar colores de widgets a partir de background/foreground/active_border
        spec["widget_bg"] = spec["background"]
        spec["widget_fg"] = spec["foreground"]
        spec["widget_border"] = spec["active_border"]

        # 3. Leer shell.bar.toml / shell.toml / shell.launcher.toml para widgets
        for s_name in ("shell.bar.toml", "shell.toml", "shell.launcher.toml"):
            s_file = t_dir / s_name
            if s_file.exists():
                try:
                    with open(s_file, "rb") as f:
                        s_data = tomllib.load(f)
                    sec = s_data.get("bar") or s_data.get("launcher") or s_data.get("menu") or {}
                    if isinstance(sec, dict):
                        if isinstance(sec.get("background"), str) and sec["background"].startswith("#"):
                            spec["widget_bg"] = sec["background"]
                        if isinstance(sec.get("text"), str) and sec["text"].startswith("#"):
                            spec["widget_fg"] = sec["text"]
                        if isinstance(sec.get("border"), str) and sec["border"].startswith("#"):
                            spec["widget_border"] = sec["border"]
                        if isinstance(sec.get("background-alpha"), (int, float)):
                            spec["widget_alpha"] = float(sec["background-alpha"])
                    break
                except Exception:
                    pass

        # 4. Leer icons.theme
        i_file = t_dir / "icons.theme"
        if i_file.exists():
            try:
                ic = i_file.read_text(encoding="utf-8").strip()
                if ic:
                    spec["icons"] = ic
            except Exception:
                pass

        # 5. Leer neovim.lua y keyboard.rgb
        nv_file = t_dir / "neovim.lua"
        if nv_file.exists():
            try:
                nv_txt = nv_file.read_text(encoding="utf-8")
                m_cs = re.search(r'colorscheme\s*=\s*"([^"]+)"', nv_txt)
                if m_cs:
                    spec["neovim_scheme"] = m_cs.group(1)
            except Exception:
                pass

        kb_file = t_dir / "keyboard.rgb"
        if kb_file.exists():
            try:
                kb_txt = kb_file.read_text(encoding="utf-8").strip().lstrip("#")
                if kb_txt:
                    spec["keyboard_rgb"] = kb_txt[:6]
            except Exception:
                pass
        else:
            spec["keyboard_rgb"] = spec["accent"].lstrip("#")[:6]

        return spec

    def list_wallpaper_options(self) -> List[str]:
        """Lista orígenes de fondos de pantalla (de cada tema y carpetas del usuario)."""
        opts: List[str] = []
        for t in self.list_available_themes():
            opts.append(f"tema:{t}")
        for u_dir in [
            Path.home() / "Pictures" / "Wallpapers",
            Path.home() / "Pictures",
            Path.home() / "Imágenes",
            Path.home() / ".local" / "share" / "omarchy" / "backgrounds",
        ]:
            if u_dir.exists() and u_dir.is_dir():
                opts.append(str(u_dir))
        return opts

    def list_custom_wallpaper_files(self) -> List[str]:
        """Lista archivos de imagen disponibles en temas y carpetas de usuario para elegir fondos o previews."""
        files: List[str] = ["ninguno"]
        search_roots = [
            Path.home() / "Pictures" / "Wallpapers",
            Path.home() / "Pictures",
            Path.home() / "Imágenes",
        ]
        for root in search_roots:
            if root.exists() and root.is_dir():
                for f in sorted(root.iterdir()):
                    if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                        files.append(str(f))
                        if len(files) >= 25:
                            break
        # También incluir algunos fondos destacados de los temas instalados
        for t in self.list_available_themes():
            t_dir = self._find_theme_dir(t)
            if t_dir and (t_dir / "backgrounds").exists():
                for f in sorted((t_dir / "backgrounds").iterdir()):
                    if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                        files.append(f"{t}/backgrounds/{f.name}")
                        break
        return files[:40]

    def create_theme_from_spec(
        self,
        spec: Dict[str, Any],
        activate: bool = False,
    ) -> tuple[bool, str]:
        """
        Crea un nuevo tema Omarchy completo en ~/.config/omarchy/themes/<slug> (y en /usr/share/omarchy/themes)
        escribiendo colors.toml, hyprland.lua (bordes activo/inactivo), shell.*.toml (fondo y borde de widgets),
        icons.theme, backgrounds/, preview.png, neovim.lua y keyboard.rgb.
        """
        raw_name = str(spec.get("name", "")).strip()
        slug = re.sub(r"[^a-z0-9\-_]", "", self.normalize_theme_slug(raw_name))
        if not slug:
            return False, "Nombre de tema invalido. Usa letras, numeros o guiones."

        dest_dir = self.user_themes_dir / slug
        if dest_dir.exists():
            return False, f"El tema '{slug}' ya existe en ~/.config/omarchy/themes."

        base_slug = self.normalize_theme_slug(str(spec.get("base_theme", self.current_theme)))
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

            # 1. Fondos de pantalla (backgrounds/)
            bg_dest = dest_dir / "backgrounds"
            bg_dest.mkdir(exist_ok=True)
            wp_source = str(spec.get("wallpapers_source", f"tema:{base_slug}"))
            if wp_source.startswith("tema:"):
                src_theme = wp_source.split(":", 1)[1]
                src_t_dir = self._find_theme_dir(src_theme)
                if src_t_dir and (src_t_dir / "backgrounds").exists() and src_t_dir != base_dir:
                    for old_f in bg_dest.iterdir():
                        if old_f.is_file():
                            old_f.unlink()
                    for img in (src_t_dir / "backgrounds").iterdir():
                        if img.is_file():
                            shutil.copy2(img, bg_dest / img.name)
            else:
                custom_dir = Path(wp_source).expanduser()
                if custom_dir.exists() and custom_dir.is_dir():
                    imgs = [p for p in sorted(custom_dir.iterdir()) if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
                    if imgs:
                        for old_f in bg_dest.iterdir():
                            if old_f.is_file():
                                old_f.unlink()
                        for img in imgs[:10]:
                            shutil.copy2(img, bg_dest / img.name)

            # Si seleccionó un archivo de fondo adicional específico
            custom_wp = str(spec.get("custom_wallpaper", "ninguno"))
            if custom_wp and custom_wp != "ninguno":
                if "/" in custom_wp and not custom_wp.startswith("/"):
                    # Formato "<tema>/backgrounds/<archivo>"
                    parts = custom_wp.split("/", 2)
                    t_src = self._find_theme_dir(parts[0])
                    if t_src and len(parts) == 3:
                        cand = t_src / parts[1] / parts[2]
                        if cand.exists():
                            shutil.copy2(cand, bg_dest / f"00-{cand.name}")
                else:
                    cand = Path(custom_wp).expanduser()
                    if cand.exists() and cand.is_file():
                        shutil.copy2(cand, bg_dest / f"00-{cand.name}")

            # 2. Preview del tema (preview.png y unlock.png)
            prev_source = str(spec.get("preview_source", f"tema:{base_slug}"))
            if prev_source.startswith("tema:"):
                p_theme = prev_source.split(":", 1)[1]
                p_dir = self._find_theme_dir(p_theme)
                if p_dir:
                    for p_name in ("preview.png", "preview-unlock.png", "unlock.png"):
                        if (p_dir / p_name).exists():
                            shutil.copy2(p_dir / p_name, dest_dir / p_name)
            elif prev_source == "usar_fondo":
                bg_imgs = sorted([p for p in bg_dest.iterdir() if p.is_file()])
                if bg_imgs:
                    shutil.copy2(bg_imgs[0], dest_dir / "preview.png")
                    shutil.copy2(bg_imgs[0], dest_dir / "unlock.png")
            else:
                p_path = Path(prev_source).expanduser()
                if p_path.exists() and p_path.is_file():
                    shutil.copy2(p_path, dest_dir / "preview.png")

            # 3. Escribir colors.toml completo (modo, acento, bordes, selección y paleta de terminal)
            mode = str(spec.get("mode", "dark"))
            accent = str(spec.get("accent", "#7aa2f7"))
            act_border = str(spec.get("active_border", accent))
            inact_border = str(spec.get("inactive_border", "#414868"))
            selection = str(spec.get("selection", "#292e42"))
            muted = str(spec.get("muted", "#414868"))
            bg = str(spec.get("background", "#1a1b26"))
            fg = str(spec.get("foreground", "#a9b1d6"))
            bright_fg = str(spec.get("bright_foreground", "#ffffff"))
            dark_bg = str(spec.get("dark_background", self.blend_hex(bg, "#000000", 0.25)))
            darker_bg = str(spec.get("darker_background", self.blend_hex(bg, "#000000", 0.50)))
            lighter_bg = str(spec.get("lighter_background", self.blend_hex(bg, "#ffffff", 0.08)))
            dark_fg = str(spec.get("dark_foreground", muted))
            light_fg = str(spec.get("light_foreground", fg))

            colors_toml_content = f'''mode = "{mode}"

accent = "{accent}"
selection = "{selection}"
muted = "{muted}"

background = "{bg}"
dark_background = "{dark_bg}"
darker_background = "{darker_bg}"
lighter_background = "{lighter_bg}"

foreground = "{fg}"
dark_foreground = "{dark_fg}"
light_foreground = "{light_fg}"
bright_foreground = "{bright_fg}"

hyprland_active_border = "{act_border}"
hyprland_inactive_border = "{inact_border}"
active_border_color = "{act_border}"

red = "{spec.get("red", "#f7768e")}"
yellow = "{spec.get("yellow", "#e0af68")}"
orange = "{spec.get("orange", "#eb927b")}"
green = "{spec.get("green", "#9ece6a")}"
cyan = "{spec.get("cyan", "#449dab")}"
blue = "{spec.get("blue", "#7aa2f7")}"
magenta = "{spec.get("magenta", "#ad8ee6")}"
brown = "{spec.get("brown", "#75493d")}"

bright_red = "{spec.get("bright_red", "#ff7a93")}"
bright_yellow = "{spec.get("bright_yellow", "#ff9e64")}"
bright_green = "{spec.get("bright_green", "#b9f27c")}"
bright_cyan = "{spec.get("bright_cyan", "#0db9d7")}"
bright_blue = "{spec.get("bright_blue", "#7da6ff")}"
bright_magenta = "{spec.get("bright_magenta", "#bb9af7")}"
'''
            (dest_dir / "colors.toml").write_text(colors_toml_content, encoding="utf-8")

            # 4. Escribir hyprland.lua con los colores de bordes de ventana enfocada e inactiva
            hyprland_lua_content = f'''local active_border_color = "{act_border}"
local inactive_border_color = "{inact_border}"

hl.config({{
  general = {{
    col = {{
      active_border = active_border_color,
      inactive_border = inactive_border_color,
    }},
  }},

  group = {{
    col = {{
      border_active = active_border_color,
      border_inactive = inactive_border_color,
    }},
  }},
}})
'''
            (dest_dir / "hyprland.lua").write_text(hyprland_lua_content, encoding="utf-8")

            # 5. Escribir configuración de fondo y bordes de widgets (shell.toml, shell.bar.toml, shell.launcher.toml, shell.menu.toml)
            w_bg = str(spec.get("widget_bg", bg))
            w_fg = str(spec.get("widget_fg", fg))
            w_border = str(spec.get("widget_border", act_border))
            w_alpha = float(spec.get("widget_alpha", 0.95))

            shell_bar_content = f'''[bar]
background       = "{w_bg}"
background-alpha = {w_alpha:.2f}
text             = "{w_fg}"
active           = "{accent}"
scale-with-font  = true
size-horizontal  = 26
size-vertical    = 28
'''
            (dest_dir / "shell.bar.toml").write_text(shell_bar_content, encoding="utf-8")

            shell_launcher_content = f'''[launcher]
background                = "{w_bg}"
background-alpha          = {w_alpha:.2f}
text                      = "{w_fg}"
border                    = "{w_border}"
border-alpha              = 1.0
scrim                     = "{bg}"
scrim-alpha               = 0.5
selected-background       = "{accent}"
selected-background-alpha = 0.15
selected-text             = "{bright_fg}"
selected-border           = "{w_border}"
selected-border-alpha     = 0.25
'''
            (dest_dir / "shell.launcher.toml").write_text(shell_launcher_content, encoding="utf-8")

            shell_menu_content = f'''[menu]
background                = "{w_bg}"
background-alpha          = {w_alpha:.2f}
text                      = "{w_fg}"
border                    = "{w_border}"
border-alpha              = 1.0
scrim                     = "{bg}"
scrim-alpha               = 0.5
selected-background       = "{accent}"
selected-background-alpha = 0.15
selected-text             = "{bright_fg}"
selected-border           = "{w_border}"
selected-border-alpha     = 0.25
'''
            (dest_dir / "shell.menu.toml").write_text(shell_menu_content, encoding="utf-8")

            # 6. Escribir icons.theme, neovim.lua y keyboard.rgb
            icons_name = str(spec.get("icons", "Yaru-blue")).strip()
            (dest_dir / "icons.theme").write_text(f"{icons_name}\n", encoding="utf-8")

            nv_scheme = str(spec.get("neovim_scheme", "tokyonight-night")).strip()
            if nv_scheme:
                nv_content = f'''return {{
  {{
    "LazyVim/LazyVim",
    opts = {{
      colorscheme = "{nv_scheme}",
    }},
  }},
}}
'''
                (dest_dir / "neovim.lua").write_text(nv_content, encoding="utf-8")

            kb_rgb = str(spec.get("keyboard_rgb", accent.lstrip("#"))).strip().lstrip("#")[:6]
            if kb_rgb:
                (dest_dir / "keyboard.rgb").write_text(f"{kb_rgb}\n", encoding="utf-8")

            # 7. Si /usr/share/omarchy/themes existe, sincronizar copia en el directorio del sistema
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
            return True, f"✓ Tema Omarchy '{slug}' creado con todos sus componentes."
        except Exception as e:
            return False, f"Error al crear el tema: {e}"

    def create_theme(
        self,
        new_name: str,
        base_theme: Optional[str] = None,
        mode: str = "dark",
        custom_colors: Optional[Dict[str, str]] = None,
        activate: bool = True,
    ) -> tuple[bool, str]:
        """Wrapper compatible que crea un tema a partir de una plantilla base."""
        spec = self.get_theme_full_spec(base_theme or self.current_theme)
        spec["name"] = new_name
        spec["mode"] = mode
        if custom_colors:
            spec.update(custom_colors)
        return self.create_theme_from_spec(spec, activate=activate)

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
