# Etapa 5.5-K-V — Prototipo de admisión remota **virtual** con proxy atestado

**Estado (13/11/2026): PROTOTIPO TESTEADO; NO DESPLEGADO.** No se encendió EC2, RDS ni el vehículo. No hay llamadas WSS ni capacidad de mover motores. El PR #5 del backend permanece en borrador y no se ha fusionado con `main`.

## Entregable digital ya protegido

La única URL que se entregará al profesor continúa siendo **https://yori7v7.github.io/control-iot-u4/**, con su repositorio **https://github.com/yori7v7/control-iot-u4**. El PR frontend #7 corrigió en `main` los 24 px de scroll detectados a **1366×680 CSS px** (ventana Windows 1365×768), además de pequeñas anomalías responsive en 320×568 y 568×320. Corrió **52 Node + 31 CONTROL + 31 MONITOREO** y se publicó vía el workflow de GitHub Pages [43393627846](https://github.com/yori7v7/control-iot-u4/actions/runs/43393627846). No se alteraron módulos JS, reglas de despacho, backend original ni secretos. El sitio público no ha habilitado todavía el acceso del invitado.

## Prototipo K-V

Nuevo módulo `app/public_control/kv_virtual_staging.py`: factory `create_kv_virtual_app(db_path, admin_proof, proxy_proof)`, NO importada por `app.main` ni por `kg_bootstrap.py`; no registra ruta de movimiento, no permite DEMO ni ESP, no crea WSS ni utiliza RDS. No se agregó script de ejecución o configuración Caddy pública.

- El app solo puede **construirse** si `APP_ENV=staging` y `ADMISSION_VIRTUAL_ONLY=enabled`, con una base SQLite absoluta fuera del repositorio y dos secretos distintos de al menos 32 caracteres. El perfil `production` queda rechazado, deliberadamente hasta auditoría.
- Se exige que la conexión HTTP al proceso provenga de **loopback**. Se verifican `Host: 100-30-4-62.nip.io`, `Origin: https://yori7v7.github.io`, y TRES encabezados que **en el futuro deberá sobrescribir un Caddy revisado**, no el navegador: `X-Admission-Proxy-Token`, `X-Admission-Client-IP` de IP pública y `X-Admission-Scheme: https`. Los encabezados proxy no confiables y cookies quedan rechazados. Comparación de la prueba del proxy en tiempo constante mediante resumen SHA-256.
- Se rechazan visitantes con `X-API-Key`, y solo el administrador presenta `X-API-Key` distinta de la clave del proxy. No se publica ninguna clave en código/HTML/README.
- `POST /publico/vehiculos/1/solicitudes` exige K-T `Idempotency-Key` y `X-Browser-Proposal`; la misma identidad + mismo par producen **un solo ticket**. `GET .../estado` usa `X-Browser-Session`, nunca un secreto en URL.
- El administrador puede listar, supervisar (15 segundos), aprobar **virtualmente** hasta 120 segundos, rechazar o revocar. Las respuestas contienen `simulado=true`, `control_fisico=false`, `canDrive=false`. `revocar` devuelve `stop_fisico_confirmado=false`.
- Se reutilizan la época durable K-Q y el journal de tickets K-R: reiniciar invalida accesos previos; una segunda instancia sobre el mismo archivo no adquiere propietario. El rate limit de K-R sigue activo por IP atestada. No sustituye controles antiabuso de borde.

## Pruebas y evidencia

`tests/test_kv_virtual_staging.py` añade seis casos: arranque protegido, solicitud y replay idempotente, autorización virtual sin motor, pérdida de permisos al reiniciar, caducidad y cuota por IP, CORS/credenciales, proxy no confiable, cliente directo remoto y rutas no existentes. Todos son **TestClient local**; no certifican al Caddy real, la seguridad de red exterior ni la integración de la interfaz completa.

[GitHub Actions 43394263034](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43394263034): **657 pruebas y 840 subpruebas aprobadas**. Ninguna acción remota sobre el vehículo.

## NO-GO: por qué aún no arrancar este prototipo en AWS

1. Faltan la configuración Caddy aprobada y cortafuegos que garanticen que el puerto interno **no pueda recibir conexiones directas**. Caddy debe **sobrescribir** todos los encabezados de identidad, esquema y prueba de proxy, sin aceptar valores enviados por Internet. No exponer el encabezado de prueba ni poner su secreto en el sitio.
2. No se ha comprobado el límite de proceso único, dueño exclusivo de SQLite en la máquina EC2, backups/permisos y persistencia tras un reinicio real. El almacén no sirve para autoridad de múltiples hosts sin coordinación distribuida.
3. No se ha integrado la página **completa** de GitHub Pages con la API, y las banderas `guestAdmissionEnabled` y `adminApprovalEnabled` permanecen desactivadas. Habilitarlas puede bloquear el CONTROL original; se requiere PR independiente y regresión.
4. El backend legacy de EC2 conserva rutas de CONTROL; nunca asumir que K-V las protege. Antes de dar acceso FÍSICO a invitados es imprescindible arbitrar Swagger, joystick, DEMO y WSS mediante una autoridad común, watchdog/interlock y STOP mecánico probado.
5. `canDrive=false` seguirá siendo cierto en esta etapa: la aprobación virtual no da permiso para mover el vehículo.

**Siguiente punto concreto:** auditoría y pruebas de la futura capa Caddy de admisión en un entorno aislado, sin cambiar todavía el Caddyfile `main`; después una prueba desde Internet, solo de tickets virtuales, y por último el frontend de Pages. Antes de modificar el entorno AWS habrá una señal de GO explícita.

Este documento es un registro de código y pruebas, **NO** un despliegue ni una autorización para abrir puertos o conectar batería.
