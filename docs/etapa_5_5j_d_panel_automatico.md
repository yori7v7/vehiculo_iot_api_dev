# 5.5-J-D — Renovación de supervisión en segunda pestaña y estado automático

**Fecha de desarrollo:** 12/11/2026. **Estatus:** corrección de la interfaz local HTML preparada en ZIP; **aún no instalada ni validada en la PC del usuario**.

## Problema reproducido conceptualmente desde el código J-C

El panel J-C invocaba `heartbeat` solo cuando `document.visibilityState !== 'hidden'`. Abrir la pestaña del invitado ocultaba la pestaña del administrador, suspendía los heartbeats y al cabo de `SUPERVISOR_TIMEOUT=15s` el backend invalidaba la sesión de invitado. El texto `Turno caducado` era consecuencia del fail-closed del servidor, no de inactividad del invitado. También había un botón `Actualizar permiso` que no era necesario para la actualización periódica si la pestaña estaba visible.

## Corrección entregada al usuario

Paquete local `Etapa_5_5_J_D_Panel_Automatico_Local.zip`:

- Script PowerShell `INSTALAR_55JD_WINDOWS.ps1` con verificación de carpeta y archivo HTML, copia `.bak_55jc_...` y reemplazo **únicamente de `invitation_lab_demo.html`** en la carpeta previa J-C.
- JS del administrador: cuando el operador pulsa `Iniciar supervisión`, se envían latidos cada 5s incluso con la pestaña en segundo plano, mientras navegador/temporizadores estén activos; el botón `Detener supervisión` los termina y el timeout de 15s se conserva. Reintento inmediato al volver a la pestaña.
- JS del invitado: elimina botón `Actualizar permiso`, actualiza el estado por sondeo cada 2s mientras la pestaña está visible y al retornar a ella; 401/403/409 invalida el token y muestra automáticamente `Turno caducado o revocado`; errores transitorios se muestran como `Sin conexión`, sin declararlos falsamente una revocación.
- El servidor HTTP, contraseñas, API key, firmware, WSS, motores y AWS permanecen sin cambios.

## Pruebas de desarrollo

- `node --check` del JS: **OK**.
- 7 pruebas HTTP existentes sobre el servidor J-C: **7 passed**.
- Simulación Node de la interfaz con DOM/fetch/temporizadores controlados: **PASS** al verificar que el heartbeat no cesa por pestaña oculta, que el invitado conserva permiso más de 15 s y que observa automáticamente una revocación sin pulsar botón.
- Chromium/Playwright **no pudo navegar ni a 127.0.0.1 ni a un dominio interceptado** en el entorno aislado del análisis (`ERR_BLOCKED_BY_ADMINISTRATOR`). **No se reivindica validación de navegador real**. Esa prueba queda para la PC del alumno.

## Nota crítica para la arquitectura final

La corrección está limitada a una **demostración local desde dos pestañas de la misma PC**. Mantener latidos con una pestaña oculta **no certifica presencia humana**; el navegador puede suspender timers de fondo y entonces el servidor debe fallar cerrado. La versión final multi-dispositivo requerirá supervisión humana activa, panel visible en dispositivo del administrador, autorización/caducidad de sesiones, STOP prioritario, watchdog físico y un único coordinador para todas las órdenes.

No se conectó este HTML a GitHub Pages, al backend AWS ni al canal físico de NodeMCU; `gpio_inhibido` sigue siendo el requisito para cualquier prueba del dispositivo.
