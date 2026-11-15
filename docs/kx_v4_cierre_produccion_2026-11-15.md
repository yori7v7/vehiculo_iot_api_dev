# K-X V4 — Cierre de publicación HTTPS virtual (15/11/2026)

**Estado confirmado por salida del operador: `K-X V4 CUTOVER CONFIRMADO` y `VALIDACION PUBLICA V4 APROBADA`.**

## Alcance

Publicar en el Caddy HTTPS 443 ya existente la admisión virtual K-V con protección de origen y autenticación, manteniendo las rutas del backend FastAPI legado. El cambio no habilita conducción física, no sustituye los motores ni implica pruebas con el carrito conectado.

- Endpoint existente: `https://100-30-4-62.nip.io/`
- Consola web de control: `https://yori7v7.github.io/control-iot-u4/` (no se afirma que la interfaz haya sido verificada en esta validación)
- Version de release usada: `scripts/kx_prod_cutover_controller_v4_RELEASE.ps1` + `scripts/kx_prod_recoverer_v4_RELEASE.ps1`.
- Paquete privado de ejecución en EC2: `C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v4_RELEASE_READY`.
- Desarrollo y registro técnico en rama `feature/kx-sidecar-windows-preparacion`. No se presume merge a `main`.

## Evidencia de cutover V4 real (salida del operador)

```text
=== K-X V4: PREFLIGHT FINAL ===
OK: Versiones y respaldos verificados
OK: HTTPS / -> 200
OK: HTTPS /openapi.json -> 200

=== INICIANDO CUTOVER REAL V4 ===
=== K-X CUTOVER COMMITTED: PUBLIC CHECKS PASSED ===

=== RESULTADO: K-X V4 CUTOVER CONFIRMADO ===
TRANSACCION: COMMITTED_VERIFIED
CADDY: RUNNING
ARCHIVOS CANDIDATOS: VERIFICADOS
HTTPS LEGADO: 200
WATCHDOG: RETIRADO
```

El controlador valida adicionalmente GET de admisión virtual K-V y los siguientes casos: administración autenticada 200 con respuesta simulada y `no-store`, sin clave 401, clave incorrecta 403, origen incorrecto 403; verifica proceso SYSTEM y propietario exacto de 443, no publicación de 9444, archivos candidatos SHA256 y ausencia del watchdog después del commit.

## Evidencia de validación final no mutadora (salida del operador)

```text
=== RESULTADO: VALIDACION PUBLICA V4 APROBADA ===
LEGADO: OPERATIVO
K-V: PUBLICADO CON PROTECCIONES
TRANSACCION: COMMITTED_VERIFIED
CONTROL FISICO: NO HABILITADO POR ESTE DESPLIEGUE
ETAPA K-X: LISTA PARA CIERRE
```

El chequeo final verificó en EC2 `COMMITTED_VERIFIED`, hashes del Caddyfile y launcher candidatos, tarea de Caddy `Running`, ausencia de watchdog residual, puerto K-V 9444 solo en `127.0.0.1`, HTTPS GET `/` y `/openapi.json` = 200, ruta administrativa GET sin clave = 401 y ruta invitada GET sin sesión = 401 con origen permitido, 403 sin origen. Solo se enviaron GET; no se crearon solicitudes ni se dispararon órdenes.

**Límite de evidencia:** la validación usó el hostname público HTTPS desde el servidor EC2; una comprobación posterior desde una red independiente o navegador es útil si se exige constancia externa. No se ejecutó un rollback real de producción ni un reboot para probar recuperación, aunque antes del corte se verificó el watchdog SYSTEM en estado PREPARED. Esta entrega NO certifica conducción física.

## Incidente corregido antes del despliegue

V3 rechazó el cambio con `ORIGINAL_PUBLIC_GET` porque exigía una ruta inexistente `/health`. La API expone salud sin RDS mediante `/` y OpenAPI mediante `/openapi.json`. El diagnóstico posterior confirmó `PREPARED`, respaldos originales intactos, Caddy `Running` y ausencia de watchdog: no ocurrió ningún corte V3. V4 corrigió preflight, salud del candidato y comprobaciones de rollback/commit, conservando versiones anteriores.

CI de V4: https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43702057983 (PASS con 45 aserciones en funciones aisladas sobre fixtures/mocks, no equivale a ensayo de fallo real del servicio).

## Decisión y operación

**K-X HTTPS virtual: CERRADA / PUBLICADA / VALIDADA** a partir de la evidencia de EC2 reportada por el operador.

- **No repetir** `Cutover` ni volver a ejecutar `-Action Review` sobre V4, ya que los originales y `PREPARED` ya no corresponden al estado activo.
- **No borrar** el paquete V4 ni sus respaldos por ahora; conservar evidencias y controles de acceso NTFS.
- **No reiniciar** ni modificar tareas, firewall, Caddy, AWS/RDS o firmware como parte del cierre.
- Mantener firmware/hardware físico en modo seguro; pruebas físicas o de aplicación frontend de usuario final quedan fuera de este cierre K-X.
- Si aparecen fallos futuros, tratar como incidente nuevo y leer estado/hashes/tareas sin relanzar automáticamente la transacción.

_Nota: el documento registra evidencia que el operador compartió desde EC2. No constituye una nueva prueba de funcionamiento realizada por GitHub._
