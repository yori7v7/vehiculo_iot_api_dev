# 5.5-K-B — HTTP local para solicitud automática en URL única

**Fecha:** 12/11/2026, hora de México. **Estado:** adaptador HTTP aislado implementado en rama experimental, **10 pruebas de integración HTTP aprobadas localmente**, sin dispositivo real. Se empaquetó una copia ejecutable en el chat del alumno.

## Objetivo de producto (para el día del examen)

- **ÚNICA URL que se entrega al profesor:** `https://yori7v7.github.io/control-iot-u4/`, sin enlaces secundarios ni códigos que deba introducir el visitante.
- El navegador visitante abre la misma interfaz Dark Red Premium (Control y Monitoreo). La página solicitará acceso automáticamente y mostrará “Esperando autorización”. Hasta que el administrador de la laptop apruebe *esa sesión concreta*, el joystick permanece bloqueado.
- El administrador, exclusivamente desde **su laptop**, puede aprobar, rechazar, revocar y supervisar. En modo supervisado no hay límite fijo de turno, pero caduca al perderse el heartbeat.
- El profesor no recibe ni conoce la API key privada.
- El ESP8266 está **por ahora en la red Wi-Fi de casa**; migración laptop + ESP8266 al hotspot del teléfono **al final de la integración, con pruebas antes del examen**, no durante la presentación.

## Entregado en K-B

- `app/public_control/single_link_http_lab.py`: FastAPI aislado con endpoints:
  - `POST /api/k/solicitud`: crea ticket anónimo en espera (no autoriza movimiento).
  - `GET /api/k/solicitud/estado`: consulta por secreto opaco de la sesión del navegador.
  - `POST /api/k/admin/supervision`: heartbeat del administrador autenticado.
  - `GET /api/k/admin/pendientes`: cola para aprobar sesión específica.
  - `POST /api/k/admin/aprobar`, `/rechazar`, `/revocar`: cambios de turno.
  - `POST /api/k/accion`: **SIEMPRE HTTP 403**, sin conexión al dispositivo.
- Se ejecuta solo explícitamente en `127.0.0.1:8767`. El HTTP bloquea cliente/Host no-loopback, Origin incorrecto, cabeceras de proxy, Sec-Fetch-Site cross-site, cuerpos excesivos; responde `Cache-Control: no-store`. No incorpora CORS público, Nginx, AWS, RDS, certificados ni firmware.
- `tests/test_single_link_http_lab.py`: **10 tests pasaron** en el contenedor local con cliente ASGI de `127.0.0.1`: espera inicial, aprobación por heartbeat, caducidad, revocación, turno temporizado, rechazo, seguridad de origen/host, privacidad de tokens, límite de cola, protección de credenciales y validación.
- El paquete `Etapa_5_5_K_B_Solicitud_Automatica_Local.zip` incluye copia del código de K-A y el adaptador K-B, pruebas, punto de inicio loopback, requisitos e instrucciones. No contiene secretos privados.

## Limitaciones y barreras pendientes

**No se puede afirmar que la URL oficial ya permita solicitar acceso real**: el adaptador K-B NO está conectado al sitio GitHub Pages, al backend productivo ni al WSS del ESP8266. K-B es solamente un prototipo HTTP autónomo con un proceso y estado en memoria; no es adecuado para despliegue multiworker ni acceso público remoto.

El adaptador no permite movimiento, ni siquiera virtual a través del WSS. Antes de conectar:
1. Integrar tickets y autorizaciones en **un coordinador único** que arbitre todos los comandos (REST admin legacy, Swagger, DEMO, joystick invitado y WSS).
2. Impedir rutas paralelas que eviten control exclusivo; asegurar recuperación/revocación transaccional y STOP prioritario.
3. Implementar watchdog local en dispositivo y pruebas eléctricas supervisadas. Los ACK `neutral_reportado_no_fisico` de 5.5-H/J no prueban parada mecánica.
4. Desarrollar frontend en rama experimental sobre el **index.html ya existente**, preservando Control, Monitoreo y el diseño. No añadir página de prueba como entrega.
5. Exponer por HTTPS con controles de seguridad y realizar ensayo desde otra laptop. Posteriormente pasar al hotspot y validar DNS/TLS/horarios/IP antes de la fecha de examen.

**Mantener `main` intacta y el PR en borrador; ninguna salida GPIO de laboratorio debe activarse.**
