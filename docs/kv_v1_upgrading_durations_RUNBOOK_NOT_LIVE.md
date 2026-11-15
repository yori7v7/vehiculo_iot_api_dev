# K-V V1 — preparación reversible de duraciones (NO CUTOVER)

**Estado:** etapa experimental, no instalar sin ventana de mantenimiento explícita. Commit candidato: `6a6e4bdf42f51f5592ded4b8186cd430920d1631` (rama `feature/kx-sidecar-windows-preparacion`). El servidor K-V público de EC2 continúa en modalidad de 120 segundos; GitHub Pages negocia las capacidades del servidor y no muestra funciones nuevas hasta que se publiquen realmente.

## Evidencia disponible
- El operador verificó en EC2 la instalación V4 `COMMITTED_VERIFIED`, Caddy, FastAPI y K-V `Running`, listener `127.0.0.1:9444`, hashes originales de ambos módulos y base privada SQLite presente.
- Hashes originales SHA-256:
  - `kv_virtual_staging.py`: `083DA2C3D359DB5631852A56126CD1522AC1B94C733AC74801362971095B307A`
  - `kr_ticket_ledger.py`: `1D7B301EEB4EF818A726010F686C325D44CF4E53CBCC6F63DC280EE09D7548D6`
- El backend candidato aprobó 26 pruebas aisladas de API, SQLite, duración, supervisión, reinicio y revocación. **No significa que el reinicio o rollback real de EC2 hayan sido probados**.

## Contrato de seguridad inalterable
1. **Solo dos fuentes K-V** se sustituyen en la futura ventana de mantenimiento. No modificar `C:\ProgramData\VehiculoIoT\Caddyfile`, lanzador Caddy, `VehiculoIoT-FastAPI`, WSS del coche, RDS, firewall ni firmware.
2. No publicar `9444`. Se mantiene el servicio `VehiculoIoT-Admission-Virtual` como cuenta dedicada `VehIoT_KXSvc`, tarea sin trigger, proceso en `127.0.0.1:9444`.
3. `config.json` contiene credenciales; jamás copiar, imprimir, subir a GitHub ni incluir en logs o chats.
4. `admission.sqlite` es el journal con época y datos de usuarios. **No copiar el archivo mientras K-V esté ejecutándose.** El repositorio usa journal SQLite `DELETE`, transacciones `BEGIN IMMEDIATE`; en una ventana futura tomar copia consistente únicamente con servicio detenido y ausencia de manejadores/conexiones, comprobar integridad y asegurar las ACL del respaldo.
5. Todo reinicio K-V revoca turnos anteriores por diseño. Se debe avisar al administrador y confirmar ventana sin usuarios antes de detenerlo.
6. Los 2/5/10/20 minutos siguen limitados por supervisión fresca (máximo 15 s); el modo indefinido prolonga una concesión de 15 s exclusivamente por latidos autenticados. El resultado siempre es `canDrive:false`.
7. El modo indefinido no debe habilitar control físico; conectar joystick al modelo autorizado exige trabajo de seguridad separado.

## Paso A — script stage-only (sin cambios de producción)
`scripts/kv_v1_upgrade_candidate_stage_only.ps1` admite `-ProbeOnly` para **únicamente leer** el baseline original, su tarea y su listener. Sin `-ProbeOnly`, tras un nuevo baseline estricto, crea exclusivamente:
`C:\ProgramData\VehiculoIoT-KV-UpgradeV1-CANDIDATE`
con ACL SYSTEM/Administradores sin herencia y descarga dos archivos con URL apuntando al commit fijo. Verifica cada hash de blob Git y escribe `candidate.json` sin secretos. **No detiene ni reinicia tareas y no toca el código activo.** Si el destino existe, falla; no pisa evidencias ni directorios.

## Requisitos para preparar cutover en etapa posterior
- Inspeccionar `candidate.json` y comparar SHA256 de fuentes inmutables.
- Auditoría NTFS real de carpeta/archivos; comprobar SID dedicado, tarea sin triggers y procesos/puertos contra `install.json`.
- Diseñar y probar recuperación K-V específica en un Windows runner o VM con tarea/SQLite ficticias (no Caddy), incluyendo cortes entre copia 1 y copia 2, fallo de arranque, falta de disco, SQLite de legado, cierre seguro y prueba de restauración real de candidatos.
- Comprobar que Windows Python existente soporta validación Pydantic `model_validator`, sin instalar dependencias nuevas en producción.
- Solo tras pruebas: autorización **separada y explícita** para detener K-V, proteger backup consistente y ejecutar el cutover K-V con controlador/recoverer verificables.
- Verificar después HTTP virtual 200/401/403, que la bandeja admin anuncia `duraciones_segundos: [120,300,600,1200]`, `modo_supervisado:true`, respuesta `canDrive:false`, revocación y ausencia de movimientos.
- Si falla: **NO-GO**; el rollback de código debe ser atómico y detener la tarea antes, nunca mezclar módulos viejo/nuevo. La nueva columna SQLite `approval_mode` es aditiva; el código anterior la ignora. No restaurar un respaldo viejo de SQLite después de aceptar tickets nuevos sin análisis de consistencia.
- Mantener el bundle HTTPS V4 `COMMITTED_VERIFIED` intacto; no volver a ejecutar su controlador ni desarmar protecciones.

## No ejecutar
- `scripts/kx_install_virtual_sidecar_loopback.ps1` (reinstala y reconstruye la cuenta/tarea).
- `scripts/kx_validate_virtual_sidecar_restart.ps1` (detiene K-V; no es preflight inocuo).
- `scripts/kx_prod_cutover_controller_v4_RELEASE.ps1` (cutover Caddy V4 ya cerrado).
- Sustituciones manuales `Copy-Item` / `Stop-ScheduledTask` sin backup ni recuperación ensayada.

**Resultado objetivo del paso A:** `GO: CANDIDATO AISLADO, FIRMAS VERIFICADAS; PRODUCCION SIN CAMBIOS.` No es autorización para publicar.
