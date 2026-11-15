# Etapa 5.5-K-I — Contrato HTTPS para la URL oficial (NO desplegado)

**Fecha:** 12/11/2026, México. **Estado:** interfaz de admisión pública *solo como contrato* en la rama experimental; inactiva por defecto y bloqueada en producción. No se encendieron AWS/RDS, ni se modificó firmware, ni la página publicada.

## Requisito del examen

El único enlace que recibirá el profesor es **https://yori7v7.github.io/control-iot-u4/**. El mismo `index.html` oficial conserva Control, Monitoreo y joystick. Al abrirlo, el navegador solicitará permiso sin introducir clave. El dueño **autorizará la solicitud individual exclusivamente desde su laptop**. El permiso de visitante no será una clave administrativa, ni se enviará en la URL. No se añadirán páginas auxiliares ni desplazamiento para utilizar el joystick.

## Contrato nuevo, implementado pero bloqueado

`app/public_control/ki_ingress.py` registra dos rutas ocultas en Swagger (compatible con `assets/js/services/GuestAdmissionService.js` del frontend):

- `POST /publico/vehiculos/1/solicitudes` (sin body, sin credenciales administrativas): devuelve HTTP 201 con un ticket opaco por navegador, `display_code` y `estado=esperando_autorizacion`; `simulado=true`, `control_fisico=false`.
- `GET /publico/vehiculos/1/solicitudes/estado`: requiere secreto temporal de navegador **solo** en `X-Browser-Session`; devuelve `esperando_autorizacion`, `autorizado` o `revocado_o_caducado` y el código. **Filtra explícitamente `guest_token`**, aunque el modelo interno lo posea.

El adaptador `GuestIngressLab` usa `controller.lock` y `controller.gate` de **la misma instancia** K-C que mantiene el WSS; no crea otra autoridad. Deniega cualquier nueva admisión si el dispositivo se desconectó. Su implementación actual es **en memoria y no apta para producción**, por lo que ningún código la instala en AWS.

### Fronteras de acceso

- `app/public_control/http.py` añade un CORS específico **solo** a `/solicitudes`: `Origin: https://yori7v7.github.io`, métodos GET/POST/OPTIONS, cabeceras `Content-Type` y `X-Browser-Session`. No permite `Authorization` o `X-API-Key` en el preflight de este recurso, y mantiene intactas las reglas de los endpoints legacy.
- La ruta exige esquema **HTTPS**, Host esperado explícito, Origin de la página oficial, no usar cookies, ni `X-API-Key`, `Authorization`, cabeceras de proxy no confiables, parámetros de consulta o secretos en URL.
- Incluye `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` y CSP restrictiva en respuestas de estos endpoints (incluidos errores y preflight).
- No publica ningún `/accion` ni permite despachar WSS/motores desde estas rutas.
- La cola de laboratorio tiene máximo cinco tickets pendientes y expiración, pero **no tiene mitigación robusta antiabuso por IP/dispositivo**: imprescindible antes de habilitar acceso real.

### Fail-closed por defecto

`app/main.py` establece:

```python
application.state.ki_ingress = None
application.state.ki_expected_host = None
application.state.ki_contract_test_enabled = False
```

El router comprueba además `app_env=development`, `legacy_handover.phase=exclusive`, `exclusive_device_control_enabled=True`, `kf_wss_controller` **idéntico al del adaptador** y `controller.connected=True`. Estas condiciones permiten pruebas instrumentadas pero deliberadamente **impiden su despliegue en producción**. La ruta se registra para validar su forma, no para operar por Internet. No existe acción pública que cambie sus banderas.

El frontend todavía mantiene `CONFIG.guestAdmissionEnabled=false`. Las solicitudes no se ejecutarán desde GitHub Pages hasta que se complete y audite el backend real.

## Verificación

- Se ejecutaron **11 pruebas de integración HTTP aisladas** sobre la implementación K-I equivalente en FastAPI, con fake de `SingleLinkAdmissionLab` y configuración CORS equivalente: **11 passed, 0 failed**. Incluyeron solicitud/espera/aprobación/revocación sin bearer de movimiento, bloqueo de desconexión y autoridad equivocada, validación Host/Origin/HTTPS, credenciales no permitidas, tamaño de cola, sesión de navegador y preflight CORS.
- Se añadieron **12 pruebas de regresión** en `tests/test_ki_public_contract.py` que importan el **ScopedControlMiddleware real del repositorio**; **pendiente ejecutar esta suite del árbol completo** en la laptop del alumno o CI. No atribuirles resultados que aún no tienen.
- Revisadas por lectura en GitHub la existencia de rutas, CORS aislado, `ki_contract_test_enabled=False` y ausencia de cambio a `main`.

## Faltantes necesarios antes de habilitar desde Internet

1. Construir una **autoridad persistente de turnos** (leases y fencing epoch), segura tras reinicios, múltiples workers y pérdida de conectividad. El modelo K-I/K-C en RAM **no es seguro** para arbitrar control remoto de motores.
2. Terminar el **control de origen y de solicitudes** detrás del reverse proxy HTTPS real: TLS, cabeceras `Forwarded` bajo allowlist de proxy, validación de Host, límites por IP/sesión y limpieza de tickets, logging privado sin tokens.
3. Diseñar autenticación de la laptop administrativa, aprobación de sesión concreta, heartbeat que confirme supervisión humana activa y aviso de revocación automática; no confundir latido de pestaña oculta con presencia humana.
4. Asegurar **un único despachador físico** para joystick administrador, Swagger, DEMO, visitante y el ESP WSS con STOP prioritario, timeout, watchdog de firmware y prueba de parada física; actualmente los ACK indican neutro virtual.
5. Unir el frontend con la API pública solo cuando exista autorización de mando segura; no habilitar joystick por un `estado=autorizado` aislado (K-H conserva `canDrive=false`).
6. Ensayar desde otra laptop y luego preparar hotspot del teléfono **antes** del examen; entregar la misma URL y no configurar nada durante la demostración.

**No desplegar este router como servicio público real, no abrir el puerto 8443 en el router, no modificar firmware ni llevar la API key al navegador del profesor. PR en borrador y ambas ramas main intactas.**
