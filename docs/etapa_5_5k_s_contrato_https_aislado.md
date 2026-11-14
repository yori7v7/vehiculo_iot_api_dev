# Etapa 5.5-K-S — Contrato HTTPS virtual con persistencia K-R (aislado)

**Estado: APROBADO EN PRUEBAS ASGI, NO DESPLEGADO.** Implementado únicamente en la rama experimental `feature/5-5a-dispositivo-protocolo-aislado`. No se modificaron `main`, GitHub Pages, EC2, RDS ni firmware. El vehículo permanece sin batería.

## Objetivo

Probar que las rutas previstas para un futuro visitante de `https://yori7v7.github.io/control-iot-u4/` pueden leer y registrar solicitudes contra un almacén SQLite durable, sin entregar la clave del administrador ni conectar el sistema de turnos a motores. El contrato virtual continúa mostrando `canDrive=false`, `simulado=true`, `control_fisico=false`.

## Implementación

- `app/public_control/ks_contract_test_app.py`: crea `create_ks_contract_test_app(...)`, un FastAPI **exclusivo de pruebas `TestClient`**, no importado por `app/main.py` ni `kg_bootstrap.py`. No hay WSS, endpoints de movimiento, Swagger legacy, DEMO ni conexión a EC2.
- Un proceso K-S abre el mismo archivo SQLite privado que `KQRestartFence`, obtiene la nueva época durable y prepara `KRTicketLedger`. Al cerrar la sesión ASGI libera el propietario; al reiniciar se invalidan tickets y permisos de la época previa.
- Peticiones públicas: `POST /publico/vehiculos/1/solicitudes` sin clave API ni cuerpo, devuelve ticket UUID, secreto de sesión una única vez y código visible. `GET .../estado` necesita únicamente `X-Browser-Session` y devuelve espera, autorización **virtual** o revocación. Secretos solo como hash en SQLite.
- Peticiones del administrador: `GET /admin/vehiculos/1/control-publico/solicitudes` lista solicitudes y estado; `POST /supervision` ratifica supervisión de 15 s; `POST /{request_id}/aprobar` admite **únicamente** modalidad `timed` de máximo 120 s; `POST /{request_id}/rechazar` rechaza un ticket; `POST /revocar` revoca todos. No finge STOP mecánico ni acuse HMAC: responde `stop_fisico_confirmado=false`.
- Protecciones de prueba: exige `https` en la URL ASGI, host exacto `ks.localhost:9443`, cliente IP loopback, origen exacto de GitHub Pages y ausencia de headers de proxy no confiable/cookies. La clave administrativa entra exclusivamente en `X-API-Key`, con comparación de resumen SHA-256; visitantes con credenciales administrativas son rechazados. CORS limitado al sitio oficial y sin credenciales de navegador. Se envían cabeceras `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`.
- `APP_ENV=production` impide construir este servidor de pruebas y la base debe estar fuera del repositorio.

## Pruebas automatizadas

`tests/test_ks_contract_test_app.py` ejecuta 7 casos adicionales:
1. Flujo integrado visitante–administrador completo con solicitud, revisión, supervisión, aprobación temporal, revocación y confirmación de permisos de movimiento **siempre inactivos**.
2. Orígenes, proxy headers, cookies, credenciales equivocadas, clientes LAN no locales, vehículos ajenos, parámetros no autorizados y solicitudes con cuerpo son rechazados.
3. CORS y clave de administrador: solicitud válida, origen ajeno rechazado, ausencia de clave `401`, clave inválida `403`.
4. Aprobaciones repetidas, duplicadas o fuera del contrato temporal no generan dos turnos virtuales.
5. Reinicio del ASGI: el secreto del visitante anterior queda inválido, el turno se cierra y el límite de solicitudes por cliente sigue vigente.
6. Caducidad y retroceso de reloj provocan cierre lógico, no autorización.
7. El módulo no se incorpora a la aplicación de producción ni expone rutas de movimiento/DEMOs/WSS.

**Evidencia CI:** [GitHub Actions 43384096724](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43384096724), commit `1725afc025ef17a61464bfc38cec041e172edd19`: **644 tests + 840 subtests aprobados**. Son **pruebas ASGI en memoria**, no una prueba del protocolo TLS con certificado real, del ESP conectado, ni del acceso del profesor desde Internet.

## Límites importantes

**No desplegar K-S en EC2 ni ejecutar `uvicorn app.public_control.ks_contract_test_app`**: la fábrica es para pruebas aisladas. El filtrado de IP loopback y los encabezados no son un sustituto de un perímetro de infraestructura.

- K-R es un registro virtual autónomo. Todavía **no** es la misma autoridad WSS K-C que gobierna el dispositivo. Un permiso del ledger **no autoriza ningún movimiento** ni es una sesión física.
- El estado virtual se puede consultar desde el navegador con el contrato de origen, pero **GitHub Pages no se conecta a un servidor privado local** por el hecho de que ASGI haya pasado sus pruebas.
- Falta idempotencia duradera de reintentos de solicitud, límites antiabuso reales por IP/proxy confiable y protección distribuida contra múltiples instancias.
- No hay certificación de seguridad física: parada mecánica, watchdog autónomo, alimentación del control, DEMO/Swagger/joystick bajo despacho único y validación en circuito.
- Un archivo SQLite local no resuelve autoridad de sesiones entre EC2 y laptop. Para acceso desde Internet hará falta una infraestructura aislada con almacén central/fencing multi-host, canal autenticado y manejo de reintentos.
- El `HTTP 503` de K-O y su STOP HMAC virtual no prueban que el carrito se haya detenido físicamente.

## Próximo incremento

**5.5-K-T — Idempotencia y reintentos del visitante sin duplicar tickets**, todavía en el mismo laboratorio ASGI/SQLite, sin red ni actuadores. Después revisar el diseño de admisión pública independiente, sin habilitar `guestAdmissionEnabled` o `adminApprovalEnabled` en GitHub Pages hasta contar con pruebas completas de infraestructura y seguridad.

**AWS/RDS apagados.** No ejecutar pasos de hardware ni abrir `8443`.
