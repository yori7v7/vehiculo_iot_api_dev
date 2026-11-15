# K-V V1 — actualización reversible de duraciones

**Estado de la entrega** · NO CUTOVER. Preparación revisable en [PR #7](https://github.com/yori7v7/vehiculo_iot_api_dev/pull/7). El operador confirmó que la instancia activa sigue en 120 segundos y que el candidato del commit `6a6e4bdf42f51f5592ded4b8186cd430920d1631` ya está aislado y auditado en EC2. Los ensayos de esta entrega se limitan a entornos aislados.

## Evidencia disponible
- El operador verificó en EC2 la instalación V4 `COMMITTED_VERIFIED`, Caddy, FastAPI y K-V `Running`, listener `127.0.0.1:9444`, hashes originales de ambos módulos y base privada SQLite presente.
- Hashes originales SHA-256:
  - `kv_virtual_staging.py`: `083DA2C3D359DB5631852A56126CD1522AC1B94C733AC74801362971095B307A`
  - `kr_ticket_ledger.py`: `1D7B301EEB4EF818A726010F686C325D44CF4E53CBCC6F63DC280EE09D7548D6`
- El backend candidato aprobó 26 pruebas aisladas de API, SQLite, duración, supervisión, reinicio y revocación. **No significa que el reinicio o rollback real de EC2 hayan sido probados**.
- El ensayo previo de recuperación aprobó 12 comprobaciones sobre copias, SQLite temporal y fallos de sustitución/arranque. [Staging y recuperación en Windows](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43711261685) · [Regresión del backend](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43711261630)
- GitHub Pages sirve el frontend publicado en `66509d7bfbdfcd34fbb69c489eec4ffccc749c2b`. El selector usa las capacidades anunciadas por K-V y conserva la opción de 120 segundos frente al contrato anterior. [Frontend publicado](https://yori7v7.github.io/control-iot-u4/) · [Implementación de negociación](https://github.com/yori7v7/control-iot-u4/blob/66509d7bfbdfcd34fbb69c489eec4ffccc749c2b/assets/js/services/AdminApprovalService.js)
- Ese commit del frontend aprobó 103 pruebas Node, cuatro de Chrome con tráfico interceptado y tres de Chrome contra FastAPI real por HTTPS efímero de loopback. La prueba integrada usa SQLite temporal. [CI del frontend](https://github.com/yori7v7/control-iot-u4/actions/runs/43708936321) · [CI integrada por HTTPS](https://github.com/yori7v7/control-iot-u4/actions/runs/43708940106)

## Contrato de seguridad inalterable
1. **Solo dos fuentes K-V** se sustituyen en la futura ventana de mantenimiento. No modificar `C:\ProgramData\VehiculoIoT\Caddyfile`, lanzador Caddy, `VehiculoIoT-FastAPI`, WSS del coche, RDS, firewall ni firmware.
2. No publicar `9444`. Se mantiene el servicio `VehiculoIoT-Admission-Virtual` como cuenta dedicada `VehIoT_KXSvc`, tarea sin trigger, proceso en `127.0.0.1:9444`.
3. `config.json` contiene credenciales; jamás copiar, imprimir, subir a GitHub ni incluir en logs o chats.
4. `admission.sqlite` es el journal con época y datos de usuarios. **No copiar el archivo mientras K-V esté ejecutándose.** El repositorio usa journal SQLite `DELETE`, transacciones `BEGIN IMMEDIATE`; en una ventana futura tomar copia consistente únicamente con servicio detenido y ausencia de manejadores/conexiones, comprobar integridad y asegurar las ACL del respaldo.
5. Todo reinicio K-V invalida las sesiones de la época anterior. Avisa a los administradores, espera que no queden usuarios ni solicitudes de prueba en curso y confirma la ventana antes de detener el servicio.
6. Los turnos de 2, 5, 10 y 20 minutos exigen supervisión vigente. El modo indefinido prolonga una concesión de 15 segundos por cada latido autenticado que llega antes del vencimiento. El resultado siempre lleva `canDrive: false`.
7. El modo indefinido no debe habilitar control físico; conectar joystick al modelo autorizado exige trabajo de seguridad separado.

## Preparación del operador

- Usa PowerShell **5.1 de 64 bits**, elevado, en la instancia Windows. Prepara una copia separada, con ACL administrativa y sin modificaciones, del commit **revisado del PR #7**. El checkout aporta los scripts, mientras que los dos módulos salen del candidato que ya existe en `C:\ProgramData\VehiculoIoT-KV-UpgradeV1-CANDIDATE`.
- Conserva `candidate.json` y los dos módulos. El controlador verifica las huellas contra la versión fijada. El script `kv_v1_upgrade_candidate_stage_only.ps1` ya cumplió su función.
- Reserva la ventana para K-V. Confirma que el entorno virtual del servicio, su cuenta, configuración, código y datos conservan su perímetro privado. Verifica que no hay solicitud ni turno en curso, que Caddy y FastAPI legado están operativos y que queda espacio para el respaldo. Conserva la copia de auditoría para poder ejecutar el recuperador aunque una consola se cierre.
- Ejecuta primero la auditoría. Comprueba el perímetro HTTPS sin enviar credenciales. Apply requiere autorización explícita y ejecuta el GET administrativo que reconcilia expiraciones y exige una bandeja sin solicitudes ni turnos.

## Actualización en la ventana autorizada

Ajusta solo la ruta de la copia administrativa y el SHA completo revisado del PR. Pega este bloque después de obtener la autorización de la ventana. Una auditoría con resultado distinto de cero detiene el bloque antes de cualquier intervención.

```powershell
$kvReviewRoot = 'C:\Auditoria\vehiculo-iot-kv-v1'
$kvReviewedCommit = '<SHA completo revisado del PR #7>'
if ($kvReviewedCommit -cnotmatch '^[0-9a-f]{40}$') { throw 'NO-GO: especifica el SHA completo revisado.' }
$kvHead = git -C $kvReviewRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $kvHead -cne $kvReviewedCommit) { throw 'NO-GO: checkout distinto del revisado.' }
$kvChanges = @(git -C $kvReviewRoot status --porcelain)
if ($LASTEXITCODE -ne 0 -or $kvChanges.Count -ne 0) { throw 'NO-GO: checkout sin verificar o con cambios.' }
$kvController = Join-Path $kvReviewRoot 'scripts\kv_v1_upgrade_controller.ps1'
powershell.exe -NoProfile -NonInteractive -File $kvController -Mode Audit
if ($LASTEXITCODE -ne 0) { throw 'NO-GO: auditoria K-V rechazada.' }
powershell.exe -NoProfile -NonInteractive -File $kvController -Mode Apply -ConfirmMaintenance
if ($LASTEXITCODE -ne 0) { throw 'NO-GO: conserva las evidencias y consulta el procedimiento de recuperacion.' }
```

El controlador respalda y comprueba la pareja original antes de detener exclusivamente la tarea dedicada de K-V. Verifica la salida de los procesos y el cierre de `9444`. Con el servicio detenido toma una copia consistente de SQLite y comprueba su integridad antes de sustituir los módulos. El controlador confirma las dos huellas de candidato antes de autorizar el arranque. La transacción privada ubicada en `C:\ProgramData\VehiculoIoT-KV-UpgradeV1-CANDIDATE\recovery` documenta el progreso. Conserva `transaction.json`, `admission.before.sqlite` y las dos fuentes respaldadas en esa carpeta.

`COMMITTED_VERIFIED` indica que el candidato arrancó, conservó la identidad y el listener esperados, migró el esquema y pasó las comprobaciones HTTPS. El estado de arranque por sí solo carece de ese alcance. Ante fallo, el controlador intenta una recuperación de código cuando la evidencia lo permite.

## Recuperación independiente

Tras un fallo o una interrupción, usa la misma copia administrativa verificada desde una nueva consola elevada. Comprueba que no queda una ejecución del controlador en curso. Conserva el estado y sus respaldos y ejecuta en la ventana autorizada:

```powershell
$kvReviewRoot = 'C:\Auditoria\vehiculo-iot-kv-v1'
$kvRecovery = Join-Path $kvReviewRoot 'scripts\kv_v1_upgrade_recover.ps1'
powershell.exe -NoProfile -NonInteractive -File $kvRecovery -ConfirmMaintenance
if ($LASTEXITCODE -ne 0) { throw 'NO-GO: conserva el estado K-V y revisa la evidencia privada.' }
```

El recuperador comprueba la transacción, la integridad de la pareja original y la compatibilidad de la base actual. Antes de reponer código verifica que K-V esté detenido y que `9444` haya quedado libre. Arranca únicamente tras comprobar las dos huellas originales. `ROLLED_BACK_VERIFIED` confirma el regreso al contrato anterior y las comprobaciones de servicio. Si alguna evidencia falta, la situación es NO-GO y no se autoriza iniciar K-V con una pareja de código sin verificar.

El rollback reusa la base vigente compatible. La columna `approval_mode` es aditiva y la versión original la ignora. Restaurar una copia SQLite antigua puede descartar solicitudes, revocaciones y aumentos de época. El recuperador conserva la copia para una intervención de datos separada si la base vigente queda dañada. Un journal auxiliar SQLite, un bloqueo activo, un esquema desconocido o un salto inesperado de época requieren NO-GO. Conserva esos archivos para el diagnóstico.

## Verificación HTTPS y de la interfaz publicada

1. Confirma que Caddy y FastAPI legado siguen activos, que HTTPS `/` y `/openapi.json` responden `200` y que el proceso dedicado de K-V posee el único listener de `9444` en `127.0.0.1`. El Caddyfile y la transacción V4 permanecen intactos.
2. Comprueba la ruta HTTPS `GET /admin/vehiculos/1/control-publico/solicitudes` desde un cliente que pase por Caddy. Con el origen de Pages y la clave administrativa correcta debe devolver `200`, `Cache-Control: no-store`, `duraciones_segundos: [120,300,600,1200]`, `modo_supervisado: true`, `simulado: true`, `control_fisico: false` y `canDrive: false`. La ruta sin clave debe responder `401` y con credencial incorrecta u origen inválido, `403`. La ruta `GET /publico/vehiculos/1/solicitudes/estado` sin sesión responde `401` con el origen de Pages. Para comprobar desde un navegador, usa la consola publicada y su entrada de clave en memoria. Mantén encabezados y cuerpos privados fuera de transcripciones, capturas, repositorios y reportes.
3. Durante una prueba funcional autorizada, abre la consola pública en dos contextos de navegador independientes para invitado y administrador. Confirma que el selector muestra **2, 5, 10 y 20 minutos** e **Indefinido bajo supervisión**. Inicia supervisión y, en cada prueba, usa una solicitud nueva cuyo código coincida en ambas vistas. Aprueba un único turno, confirma que aparece autorizado virtualmente y comprueba que los controles de movimiento siguen deshabilitados. Usa otro contexto de invitado para comprobar que una segunda solicitud permanece en espera mientras el primer turno se conserva. Revoca antes de la siguiente prueba. La respuesta de revocación informa `stop_fisico_confirmado: false`.
4. Para verificar caducidad por latidos, interrumpe la red de la pestaña administrativa mientras el invitado conserva conexión y espera al menos 15 segundos **desde el último latido aceptado**, más el tiempo de sondeo de la vista. El turno debe figurar como revocado o caducado. Restablece la supervisión y verifica que el turno anterior sigue inválido. Completa la prueba con un turno nuevo. La prueba automatizada con reloj simulado cubre todo el plazo de cada opción temporal. Para medir los vencimientos absolutos en EC2, mantén la supervisión durante toda la duración elegida y registra la caducidad con margen para el sondeo. Las comprobaciones de reinicio pertenecen al laboratorio y a la transición ya autorizada.
5. Revoca los turnos de prueba, termina supervisión y confirma que la bandeja y la ocupación están vacías. Registra solo códigos HTTP, capacidades, estados y fases de transacción. Los tiempos observados por el navegador incluyen su sondeo.

## Condiciones de decisión

- **GO para Apply** requiere auditoría aprobada, ventana autorizada y bandeja sin solicitudes ni turno en curso. K-X V4 debe seguir `COMMITTED_VERIFIED`.
- **GO operativo** requiere la fase `COMMITTED_VERIFIED` de **K-V V1** y las comprobaciones posteriores del operador. Certificados, DNS público, ACL, tareas y procesos de EC2 se verifican en su contexto real solo en esa ventana.
- **NO-GO** ante hashes, identidad, ACL, procesos, listener, esquema, respaldo o HTTPS no verificables. Conserva la evidencia. Si un fallo dejó K-V detenido, mantenlo así hasta comprobar la recuperación. Si la detención misma falla, verifica el estado real antes de intentar recuperar. Un reinicio posterior del host requiere revisión por el operador porque la tarea original carece de disparador de arranque.
- **Reejecución.** La carpeta de recuperación contiene una transacción única. Si Apply se interrumpe, revisa el estado con el recuperador independiente. Conserva el respaldo aun si la recuperación fue satisfactoria.

## No ejecutar
- `scripts/kx_install_virtual_sidecar_loopback.ps1` (reinstala y reconstruye la cuenta/tarea).
- `scripts/kx_validate_virtual_sidecar_restart.ps1` (detiene K-V; no es preflight inocuo).
- `scripts/kx_prod_cutover_controller_v4_RELEASE.ps1` (cutover Caddy V4 ya cerrado).
- Sustituciones manuales `Copy-Item` / `Stop-ScheduledTask` sin backup ni recuperación ensayada.

El operador conserva la evidencia del staging original `GO: CANDIDATO AISLADO, FIRMAS VERIFICADAS; PRODUCCION SIN CAMBIOS.` La autorización para Apply corresponde a la ventana de mantenimiento de K-V.
