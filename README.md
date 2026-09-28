# Meca HyprConfig (MECA) 🖥️✨

**Panel TUI Monolítico de Configuración y Personalización para Hyprland + Omarchy**

<p align="center">
  <img src="https://raw.githubusercontent.com/leonardo/meca-hyprconfig/main/preview.png" alt="Meca HyprConfig" width="700" onerror="this.style.display='none'">
</p>

---

## 🎯 ¿Por qué Meca HyprConfig?

En sistemas basados en **Omarchy** y **Hyprland**, configurar monitores, bordes de ventanas, animaciones, atajos y temas normalmente exige editar archivos de configuración en formato texto (`.lua` / `.conf`). Para desarrolladores esto puede ser entretenido, pero para un usuario nuevo representa una gran barrera de entrada.

**Meca HyprConfig** elimina esta fricción mediante una interfaz de terminal (**TUI**) hermosa, reactiva y monolítica, que permite calibrar y personalizar todo el entorno visualmente en tiempo real.

---

## 🚀 Características Principales

1. **🖥️ Gestión Visual de Monitores & Displays:**
   - Detección automática de pantallas conectadas vía `hyprctl`.
   - Ajuste de resolución, tasa de refresco (Hz) y escala (HiDPI: 1.0x, 1.25x, 1.5x, 2.0x).
   - Persistencia limpia en `~/.config/hypr/monitors.lua`.

2. **🎨 Apariencia & Temas Reactivos:**
   - **Reactividad instantánea:** Adapta la paleta de colores de la TUI leyendo el tema de Omarchy en uso (`colors.toml`).
   - Calibración en caliente con vista previa visual de:
     - Separación exterior (`gaps_out`) e interior (`gaps_in`).
     - Esquinas redondeadas (`rounding`).
     - Grosor del borde de ventanas (`border_size`).
     - Atenuación de ventanas inactivas (`dim_inactive`).
   - Selector integrado para cambiar entre todos los temas de Omarchy (`omarchy theme set`).

3. **⚡ Animaciones y Fluidez:**
   - Activación o desactivación global de animaciones.
   - Presets de velocidad: **Fluido** (*smooth*), **Ultra Rápido** (*snappy*) o **Sin Animaciones** (*off* para equipos de bajos recursos).

4. **⌨️ Corrección de la Tecla Bloq Mayús (Caps Lock):**
   - **Problema resuelto:** Omarchy por defecto convierte la tecla Bloq Mayús en tecla compuesta (`compose:caps`), impidiendo su uso normal.
   - **Solución Meca:** Reasigna la tecla compuesta a **Alt Gr / Alt Derecha** (`compose:ralt`), liberando la tecla Bloq Mayús para que recupere su funcionamiento 100% natural.

5. **🛡️ Setup & Identidad Lizarbe:**
   - Activador del tema oficial **Lizarbe** y **Lizarbe Light** con iconos `Lizarbe-Red`.
   - Verificación y enlace automático del logo ASCII de Lizarbe en Fastfetch (`~/.config/fastfetch/logo.txt`).
   - Panel de estado de software amigable recomendado (Nautilus, Pavucontrol, Navegadores, etc.).

6. **🔄 Auto-Actualización con Omarchy:**
   - Se integra en el ciclo de vida del actualizador nativo de Omarchy.
   - Registra un hook en `~/.config/omarchy/hooks/post-update.d/99-meca-hyprconfig.sh` que se dispara automáticamente cada vez que corres `omarchy update`.

---

## 📦 Instalación Rápida

Clona el repositorio o ejecuta dentro del directorio del proyecto:

```bash
cd meca-hyprconfig
./install.sh
```

El instalador:
1. Crea los enlaces simbólicos `meca` y `meca-hyprconfig` en `~/.local/bin/`.
2. Registra la entrada de escritorio `Meca HyprConfig` en el lanzador de aplicaciones (SUPER + SPACE).
3. Instala el hook post-update en Omarchy.
4. Conecta modularmente `~/.config/hypr/hyprland-gui.lua` con tu `hyprland.lua`.
5. Aplica de inmediato la liberación de la tecla Bloq Mayús.

---

## 🕹️ Modos de Uso

### 1. Interfaz Interactiva (TUI)
Para abrir el panel de control:
```bash
meca
```
*O búscalo como **Meca HyprConfig** en el menú de aplicaciones.*

#### Botones Físicos de Acción y Navegación:

- **🔘 Botones Físicos en Pantalla:**
  - **`[ Restablecer (r) ]`:** Restaura inmediatamente todos los valores a los valores predeterminados de Omarchy / Hyprland.
  - **`[ Cancelar (c) ]`:** Revierte cualquier cambio no guardado al estado en que se abrió la aplicación.
  - **`[ Guardar (s) ]`:** Escribe la configuración en `~/.config/hypr/hyprland-gui.lua` y la aplica en vivo a Hyprland.

- **🖱️ Interacción con Ratón:**
  - **Clic en botones físicos:** Haz clic directamente sobre `[ Restablecer ]`, `[ Cancelar ]` o `[ Guardar ]`.
  - **Clic en la barra lateral:** Cambia de categoría/sección instantáneamente.
  - **Clic en steppers `[ - ]` y `[ + ]`:** Incrementa o disminuye el valor.
  - **Clic en conmutadores `[ ■ ] ON` / `[   ] off`:** Activa o desactiva la opción.
  - **Clic en selectores `[ <opción> v ]`:** Cicla entre las opciones disponibles.
  - **Arrastre en sliders:** Ajusta el nivel arrastrando el puntero sobre la barra.
  - **Rueda del ratón (Scroll):** Desplaza secciones o calibra valores numéricos.

- **⌨️ Teclado:**
| Tecla | Acción |
|---|---|
| `Tab` | Alternar foco entre Sidebar, Panel de Ajustes y Botones Físicos |
| `↑` / `↓` | Seleccionar categoría u opción |
| `←` / `→` | Ajustar valor / navegar entre botones |
| `Enter` o `Espacio` | Activar opción o pulsar el botón seleccionado |
| `s` | Guardar configuración y aplicar en caliente |
| `c` | Cancelar cambios y revertir |
| `r` | Restablecer a valores por defecto de Omarchy |
| `q` o `Esc` | Salir del panel |

### 2. Comandos CLI Directos
```bash
# Ver estado del sistema y configuración actual
meca --status

# Liberar la tecla Bloq Mayús (Compose en Alt Gr)
meca --fix-caps

# Aplicar el tema Lizarbe oficial e iconos
meca --apply-lizarbe

# Ejecutar la preparación completa para nuevos usuarios
meca --setup
```

---

## 🧱 Arquitectura del Proyecto

```text
meca-hyprconfig/
├── bin/
│   ├── meca-hyprconfig         # Lanzador ejecutable con entorno Python
│   └── meca                    # Enlace simbólico corto
├── meca/
│   ├── __init__.py             # Versión y metadatos del paquete
│   ├── cli.py                  # CLI y procesamiento de argumentos
│   ├── core/
│   │   ├── config_sync.py      # Persistencia en hyprland-gui.lua y monitors.lua
│   │   ├── hypr_ipc.py         # Comunicación en tiempo real con hyprctl
│   │   ├── lizarbe_manager.py  # Gestión de temas Lizarbe, fastfetch y apps
│   │   └── theme_engine.py     # Parser de colors.toml y paleta TrueColor ANSI
│   └── ui/
│       └── tui.py              # Motor TUI monolítico reactivo (cero dependencias)
├── hooks/
│   └── 99-meca-hyprconfig.sh   # Hook de auto-actualización para 'omarchy update'
├── install.sh                  # Instalador automatizado para el sistema
├── meca.desktop                # Acceso directo para el lanzador de Omarchy
└── README.md
```

---

## 📄 Licencia

Desarrollado con dedicación para la comunidad de **Omarchy** y el ecosistema **Lizarbe**.
Licencia MIT.
