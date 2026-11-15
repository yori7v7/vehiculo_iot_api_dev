# 5.5-J-B — Contrato aislado de invitaciones y plan para el enlace público

**Estado:** módulo puro de autorización agregado en rama experimental (NO conectado a rutas HTTP, AWS, GitHub Pages ni motores). Diez pruebas unitarias locales verificadas sobre el código del módulo; no equivalen a pruebas del frontend ni del ESP8266.

## Lo que ya existe en el código

- `app/public_control/invitation_lab.py`: `GuestInvitationLab`, tokens aleatorios de un solo uso (guardados en forma de SHA-256), canje atómico en una sesión de invitado independiente, modo `timed` (hasta 300 s) o `supervised` sin duración fija, expiración de enlace hasta 300 s.
- Supervisor: latido autorizado cada 5 s desde la capa llamadora, presencia válida durante 15 s; la sesión del invitado caduca si deja de haber latidos. El modelo de dominio NO verifica presencia física humana.
- Revocación administrativa, desconexión del administrador o del dispositivo invalidan permisos y exigen confirmación de neutro lógico antes de conceder otro invitado.
- Diez pruebas: necesidad de supervisor/autorización, token un solo uso, sesiones opacas, invitado supervisado mantenido bajo heartbeats, caducidad, revocación, corte del dispositivo, modo temporal, enlace rotado, retroceso de reloj y bloqueo de nuevo invitado hasta confirmación de neutro.
- No existe ruta que invoque este módulo desde la web: **no tiene autoridad sobre el vehículo** y no debe presentarse como invitación utilizable.

## Integración pendiente para que el profesor abra un enlace

1. **Crear invitación administrativa:** petición HTTPS del panel protegido por X-API-Key al backend; el servidor verifica que el admin haya elegido un modo, vigencia de invitación breve y dispositivo autenticado en el coordinador único.
2. **Entregar enlace por fragmento:** URL propuesta `https://yori7v7.github.io/control-iot-u4/?modo=invitado#invitacion=<token>`. El token temporal es un ejemplo de posición, NO una URL operativa. JS debe borrar inmediatamente el fragmento con `history.replaceState` tras recibirlo para reducir exposición en historial/capturas.
3. **Canjear desde el navegador:** POST HTTPS al endpoint futuro de canje (no existe todavía); devuelve un **bearer de turno** distinto de la API key administrativa. Evitar persistir bearer en almacenamiento local y proponer renovación controlada.
4. **Una única fuente de arbitraje:** cualquier movimiento del admin legacy/Swagger, demo, invitado o joystick debe pasar por el mismo coordinador con época/generación y prioridades. Actualmente los endpoints heredados NO están unificados; conectar el invitado directamente sería inseguro.
5. **Presencia del supervisor:** mantener heartbeat cada 5 s desde una sesión administrativa activa, expirar a 15 s; bloquear si el panel se oculta/cierra o se pierde la sesión. No basarse solamente en un programa `vigilar` que puede seguir ejecutándose sin persona.
6. **Observación simultánea:** ambos navegadores pueden consultar datos de estado de solo lectura; solo un operador activo emite movimiento.
7. **STOP real y fail-safe:** ruta de STOP preemptiva que invalide inmediatamente permisos y movimientos; watchdog local de firmware independiente del ping WSS de 5 s; pruebas de desconexión, brownout, reinicio y cortocircuitos con carga supervisada. Un ACK de `neutral_reportado_no_fisico` NO verifica inmovilidad mecánica.
8. **Despliegue:** no habilitar endpoints HTTP públicos ni llevar los secretos de LAN a AWS hasta superar pruebas de integración simulada, autenticación, revocación, carril prioritario de STOP y circuitería física.

## Estado actual de frontend y backend

El frontend `control-iot-u4` de GitHub Pages tiene `index.html` en raíz y JS en `assets/js`. Su `app.js` restringe el modo `?modo=turnos` a `localhost`; el servidor `app/public_control/http.py` también fuerza loopback para los endpoints simulados. **Ese bloqueo se conserva intencionalmente.** El `main` de frontend y backend sigue intacto.

## Comprobación del alcance

El módulo no contiene GPIO, servidores WSS, dependencia de RDS ni rutas FastAPI. Un tercero que abra hoy el enlace del proyecto NO tendrá acceso al nuevo flujo de invitaciones; el acceso público seguro todavía requiere implementación y pruebas. Ninguna credencial de Wi-Fi, certificado privado, token real ni API key forma parte del repositorio.
