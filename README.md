# Meca HyprConfig (MECA)

**Panel TUI Monolítico de Configuración y Personalización para Hyprland + Omarchy**

---

## ¿Por qué Meca HyprConfig?

En sistemas basados en **Omarchy** y **Hyprland**, configurar monitores, bordes de ventanas, animaciones, atajos, procesos de inicio y temas exige editar archivos de configuración en formato texto (`.lua` / `.toml`). Para usuarios nuevos esto representa una barrera de entrada innecesaria.

**Meca HyprConfig** elimina esta fricción mediante una interfaz de terminal (**TUI**) sobria, reactiva y monolítica, que se abre como una ventana flotante y centrada y permite calibrar todo el entorno con el ratón o el teclado.

---

## Características Principales

1. **Ventana Flotante y Centrada:**
   - Se ejecuta automáticamente en modo ventana flotante y centrada (`960x680`) mediante `hyprctl` y reglas nativas de Omarchy (`TUI.float` / `org.omarchy.meca`).

2. **Gestión de Autostart (`~/.config/hypr/autostart.lua`):**
   - Permite agregar nuevas **aplicaciones/servicios** (`o.launch_on_start`) o **comandos/scripts** (`o.exec_on_start`) mediante una ventana modal interactiva.
   - Permite activar, desactivar o eliminar procesos de inicio existentes (`Supr` / `x`).

3. **Sección Omarchy y Edición de Temas Originales:**
   - Selector de tema activo de Omarchy (`omarchy-theme-set`).
   - Editor de propiedades del tema (`mode`, `accent`, `background`, `foreground`, `selection`, `icons.theme`) y editor de código Hex personalizado (`#RRGGBB`) que actualiza tanto la copia de usuario (`~/.config/omarchy/themes/<tema>`) como el tema original y el tema activo en tiempo real.
   - Acciones rápidas para alternar fondo de pantalla (`omarchy-theme-bg-next`), barra superior (`omarchy-toggle-bar`), luz nocturna (`omarchy-toggle-nightlight`) y aplicar el setup **Lizarbe**.

4. **Corrección de la Tecla Bloq Mayús (Caps Lock):**
   - Reasigna la tecla compuesta a **Alt Gr / Alt Derecha** (`compose:ralt`), liberando la tecla Bloq Mayús para que recupere su funcionamiento normal.

5. **Controles en Cuadrados Cerrados y Ventanas de Confirmación:**
   - Botones de acción compactos con bisel 3D Unicode (`Restablecer`, `Cancelar`, `Aplicar`) y controles en cuadrados cerrados de 3 líneas.
   - Ventana modal de confirmación al cambiar de sección con cambios sin aplicar (`Descartar`, `Cancelar`, `Aplicar`) y al restablecer valores por defecto.
   - El botón `Cancelar` revierte cambios pendientes y cierra la ventana.

---

## Instalación Rápida

```bash
cd meca-hyprconfig
./install.sh
```

---

## Modos de Uso

### 1. Interfaz Interactiva (TUI)
```bash
meca
```

| Tecla / Control | Acción |
|---|---|
| Clic izquierdo / Rueda | Navegar secciones, ajustar valores, arrastrar sliders y pulsar botones |
| `Tab` | Alternar foco entre Barra Lateral, Panel de Ajustes y Botones |
| `↑` / `↓` / `←` / `→` | Seleccionar categoría, opción o ajustar valor |
| `Enter` o `Espacio` | Activar opción o pulsar el botón seleccionado |
| `a` o `s` | Aplicar configuración en Hyprland y Omarchy |
| `c` | Cancelar cambios pendientes y cerrar la ventana |
| `r` | Restablecer a valores por defecto (con confirmación) |
| `Supr` o `x` | Eliminar entrada seleccionada en la sección Autostart |
| `q` o `Esc` | Salir del panel |

### 2. Comandos CLI Directos
```bash
# Ver estado del sistema y configuración actual
meca --status

# Liberar la tecla Bloq Mayús (Compose en Alt Gr)
meca --fix-caps

# Aplicar el tema Lizarbe e iconos
meca --apply-lizarbe

# Ejecutar la preparación completa para nuevos usuarios
meca --setup
```
