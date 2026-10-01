# MECA (Meca HyprConfig)

> Panel TUI moderno, reactivo y ligero para configurar y personalizar **Hyprland** y el ecosistema **Omarchy**.

---

## ⚡ Características

- **Diseño TUI Nativo:** Interfaz flotante con soporte completo de ratón (clic, arrastre) y teclado.
- **Personalización Visual:** Ajuste en vivo de gaps, bordes, esquinas, blur, opacidad y animaciones.
- **Monitores & Pantallas:** Resolución, tasa de refresco (Hz), escala fraccional, rotación y VRR.
- **Gestor de Atajos (Keybinds):** Grabación en vivo de combinaciones de teclas y catálogo de aplicaciones.
- **Autostart:** Gestión gráfica de apps y scripts en `~/.config/hypr/autostart.lua`.
- **Estudio de Temas Omarchy:** Cambio rápido de temas, edición de paletas HEX y creación de temas propios.
- **Teclado & Entrada:** Calibración de sensibilidad, distribución (layout) y corrección de tecla Bloq Mayús / Compose (`Alt Gr`).
- **Barra Waybar:** Control de visibilidad, modo opaco, luz nocturna y reinicio rápido del shell.

---

## 🚀 Instalación

Copia y pega en tu terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/lizarbe513/Meca-HyprConfig/main/install.sh | bash
```

> **Opcional (Manual):**
> ```bash
> git clone https://github.com/lizarbe513/Meca-HyprConfig.git && cd Meca-HyprConfig && ./install.sh
> ```

El script clona el proyecto en `~/.local/share/meca-hyprconfig`, enlaza `meca` en `~/.local/bin/`, registra el acceso de escritorio y configura las reglas de ventana para Hyprland.

---

## 🕹️ Uso

### Interfaz Gráfica (TUI)

Ejecuta el panel desde tu terminal o lanzador de aplicaciones (Walk/Rofi):

```bash
meca
```

#### Atajos de Navegación

| Tecla / Control | Acción |
| :--- | :--- |
| **Clic / Arrastre** | Navegar, mover sliders, desplegar menús y pulsar botones |
| `Tab` / `Shift+Tab` | Alternar foco entre panel lateral, ajustes y botones |
| `↑` / `↓` / `←` / `→` | Navegar opciones o ajustar valores |
| `Enter` / `Espacio` | Seleccionar / activar elemento |
| `a` | **Aplicar** configuración en el sistema |
| `c` | **Cancelar** cambios pendientes y salir |
| `r` | Restablecer a valores por defecto |
| `q` / `Esc` | Cerrar panel |

---

### Línea de Comandos (CLI)

MECA también incluye utilidades directas por terminal:

```bash
meca --status         # Muestra el estado del entorno y configuraciones
meca --fix-caps       # Restaura Bloq Mayús y libera Alt Gr (@)
meca --apply-lizarbe  # Aplica la paleta y configuración Lizarbe
meca --setup          # Configuración inicial recomendada
```

---

## 📋 Requisitos

- **OS:** Linux (optimizado para Arch Linux / Omarchy)
- **Compositor:** Hyprland
- **Python:** 3.10+
- **Herramientas de entorno:** `hyprctl`, `uwsm` (opcional pero recomendado)

---

## 📄 Licencia

MIT © [lizarbe513](https://github.com/lizarbe513)
