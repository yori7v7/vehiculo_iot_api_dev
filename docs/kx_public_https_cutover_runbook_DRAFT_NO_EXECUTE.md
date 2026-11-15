# K-X: runbook de cambio HTTPS público — BORRADOR / NO EJECUTAR

**Estado**: `DRAFT_NO_EXECUTE`. Este documento NO autoriza reinicio, publicación, recarga ni sustitución de archivos. El control físico seguirá deshabilitado. El objetivo es publicar únicamente las rutas virtuales K-V en el Caddy existente, con recuperación real de HTTPS/legado.

## Evidencias obtenidas (aún NO prueban el cutover real)

1. `proxy_proof` rotado: token antiguo rechazado (403), token nuevo aceptado (200), autosave del perfil Administrador retirado.
2. Caddy real en loopback `127.0.0.1:9481` autenticó K-V 200/401/403, rechazó `Origin` incorrecto y filtró cabeceras de spoofing; token ausente de archivos inspeccionados.
3. Candidato HTTPS completo ensayado bajo `SYSTEM`, ambos upstreams `127.0.0.1:9444` y `127.0.0.1:8000`; fallback a FastAPI 200 y rutas K-V autenticadas; tarea y servidor temporales eliminados.
4. El lector de `proxy_proof` del lanzador candidato fue ejecutado bajo `SYSTEM`; variable de entorno heredada por proceso hijo sin escribir la credencial.
5. `Write-VehicleProcessRecord` de `deploy/windows/common.ps1` creó y actualizó correctamente registros dummy en Windows PowerShell 5.1. **No modificar el helper por esta hipótesis**. La variante `[NullString]::Value` probada es diferente del `$null` que previamente dio error 87 en otros scripts.
6. El Caddyfile original y `run_caddy.ps1` productivo permanecieron íntegros. Ninguna de estas pruebas demuestra todavía el ciclo real detener/rearrancar la tarea `VehiculoIoT-Caddy`, ni TLS/ACME desde Internet.

## Archivos/productos que se deben preservar

| Elemento | Ruta | Restricción |
|---|---|---|
| Caddyfile original | `C:\ProgramData\VehiculoIoT\Caddyfile` | Respaldar y comparar con `install.json.original_caddy_sha256` |
| Lanzador original | `C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1` | Hash esperado antes del cutover: `873840E12E08A885D1D20478E6415D6707875D72856F473094C45DB7CAA44BA1` |
| Helper existente | `C:\vehiculo_iot_api_dev\deploy\windows\common.ps1` | **NO reemplazar** |
| Respaldo de tarea | `C:\ProgramData\VehiculoIoT-KX-Installer\kx_caddy_release_preflight\VehiculoIoT-Caddy.task.xml` | Leer y conservar, no registrar otra tarea de producción |
| Respaldo Caddy anterior | `C:\ProgramData\VehiculoIoT-KX-Installer\kx_caddy_release_preflight\Caddyfile.original.copy` | Verificar SHA256 |
| Caddyfile candidato | `C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_public_release_v1_offline\Caddyfile.kx.ready.NOT_ACTIVE` | Solo placeholder `{env.KX_STAGING_PROXY_PROOF}`, nunca token literal |
| Lanzador candidato | `C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_public_release_v1_offline\launcher_staging_v1\run_caddy.kx.pending.ps1` | Lee token privado bajo SYSTEM y deja proof inválido si hay fallo |
| K-V privado | `C:\ProgramData\VehiculoIoT-KX-State\service\config.json` | No imprimir, exportar, incorporar a Caddyfile o logs |
| Autosave Caddy productivo | `C:\ProgramData\VehiculoIoT\caddy-config\caddy\autosave.json` | No editar; verificar sin token |

La tarea `VehiculoIoT-Caddy` usa un supervisor PowerShell y el helper `Invoke-VehicleProcess`, que mantiene un registro bajo `C:\ProgramData\VehiculoIoT\run\caddy.json`. Un procedimiento de despliegue **no debe** asumir que detener la tarea mata automáticamente el proceso hijo; debe verificar PID, creation_ticks y executable_path antes de manipular el proceso registrado. No usar `taskkill /IM caddy.exe`, `Stop-Process` indiscriminado ni tocar `VehiculoIoT-FastAPI` o `VehiculoIoT-Admission-Virtual`.

## Fase 0 — Bloqueos imprescindibles antes de solicitar una ventana de intervención

- Confirmar autorización explícita para una **interrupción breve del HTTPS público** y disponibilidad de consola administrativa/RDP.
- Validar hostname/certificados HTTPS actuales y que el DNS/Elastic IP sigan correspondiendo a la instancia.
- Verificar una sola instancia Caddy original y su propietario `SYSTEM`; listeners `443`, `8000`, `9444` y ausencia de `9481`.
- Verificar archivos fuente y candidatos con hashes SHA256 y evidencia de los experimentos; ninguno debe haberse cambiado desde el preflight.
- Verificar rollback COMPLETO: copias originales, ACL NTFS, definición de tarea y capacidad de arrancar el original bajo `SYSTEM`.
- Confirmar que no hay tickets `waiting`/`approved_virtual` ni sesiones virtuales activas.
- Comprobar que la tarea `VehiculoIoT-Caddy` usa `-RestartCount 999` y `-RestartInterval 1 min`, por lo que el despliegue debe prevenir la carrera de autorreinicio mientras dure la transición. **No improvisar** `Stop-ScheduledTask` + sustitución sin control de ownership/estado.
- Prevalidar sintaxis de Caddy **candidato exacto** sin exponer token: `caddy adapt/validate`; comprobar `persist_config off`, admin en loopback, dos upstreams y reglas de cabeceras.
- Confirmar fail-closed si no se puede leer el proof privado. Comprobar que la URL de legado permanece accesible con K-V aislado.
- Mantener firmware ESP, batería, RDS y motores OFF. Prohibido cambiar reglas del firewall/router para `9444` o `9481`.

**Cualquier falla = NO-GO.** No instalar candidato, no detener tarea, no abrir puertos.

## Fase 1 — Pre-armar recuperación antes de tocar HTTPS

El procedimiento de cutover debe crearse como **script independiente de retorno** y ejecutarse/validarse en laboratorio contra rutas ficticias antes de afectar producción. Preparar una copia protegida e inmutable de los dos archivos originales, con hash almacenado sin secretos. Asegurar recuperación disponible incluso si el script de activación falla a mitad del proceso, se cierra la consola o hay timeout. El script de recuperación no debe depender de que K-V esté sano ni de una variable de entorno válida.

Definir validaciones posteriores al rollback: HTTPS `443` vuelve a escuchar por un único Caddy bajo `SYSTEM`, Caddyfile y lanzador originales vuelven a hashes exactos, GET de legado funciona y las tareas originales permanecen operativas. Una falla en la restauración es una incidencia operativa, **no un éxito parcial**.

## Fase 2 — Cutover atómico, en una ventana aprobada (todavía NO implementado)

1. Congelar modificaciones concurrentes y reconocer posibilidad de interrupción temporal de HTTPS.
2. Detener únicamente el supervisor Caddy de modo controlado y verificar fin del proceso hijo registrado antes de cambiar archivos. Gestionar reintentos automáticos y documentar la definición original de la tarea.
3. Sustituir **dos** archivos (`Caddyfile` y `run_caddy.ps1`) mediante operaciones NTFS con backup explícito, hashes exactos y limpieza segura del backup temporal. Es una operación de varios archivos: **NO es atómica en conjunto**; si falla el segundo cambio, ejecutar rollback de ambos antes de reanudar.
4. Comprobar permisos, ausencia de tokens literales en los archivos y que `common.ps1` permanezca idéntico.
5. Iniciar Caddy por la misma tarea original, bajo `SYSTEM`, inyectando token únicamente desde la configuración privada al entorno del proceso hijo.
6. No editar `VehiculoIoT-FastAPI` ni la tarea/DB de K-V.

## Fase 3 — Verificación posterior a cutover y GO

Probar inmediatamente (sin acciones POST):
- Servicio HTTPS `443`, certificado/TLS vigente, dominio esperado y ausencia de segundo Caddy.
- Rutas de legado `/health` y `/openapi.json` con HTTP 200; distinguir error upstream, certificado y HTTP de aplicación.
- K-V: admin autorizado 200; sin clave 401; clave falsa 403; origin inválido 403; cabeceras proxy falsas ignoradas; bloqueo de documentación del sidecar; no-store.
- Rechazo directo a `127.0.0.1:9444` sin token y ausencia de exposición pública de `9444`, `9481` y admin 2019.
- K-V responde `simulado=true`, `control_fisico=false`, `canDrive=false`, sin tickets activos.
- Revisión acotada de logs/autosave para detectar secretos. No volcar logs completos, tokens ni cabeceras sensibles a consola.
- Un fallo crítico en cualquiera de estas comprobaciones exige **rollback**, no declarar GO.

## Fase 4 — Rollback operativo

Restaurar ambos originales de las copias verificadas, con su propietario y ACL correctos; volver a iniciar el supervisor Caddy con la tarea original y verificar 443/legado, sin K-V público. El watchdog de recuperación debe ejecutarse fuera del árbol que detiene el supervisor Caddy y tener un mecanismo claro para evitar una recuperación simultánea con el cutover. Debe actuar incluso si el proceso de despliegue se interrumpe. Nunca restaurar una copia secreta histórica; solo Caddyfile y lanzador originales.

**Aún NO hay prueba de rollback real del supervisor Caddy ni experiencia de arranque productivo de la configuración modificada.** No declarar finalizado despliegue ni seguridad por las simulaciones actuales.

## Política de autorización

Permanecer en `NO-GO_PUBLICACION` hasta que (1) exista un procedimiento de cutover y rollback ensayado en aislamiento y protegido frente a interrupción, (2) se verifiquen hashes/tareas/sesiones y (3) el operador autorice expresamente una ventana para posible caída del HTTPS público. La publicación del control físico está completamente fuera de alcance.

## Avance posterior: laboratorio de rollback doble (NO ACTIVA PRODUCCION)

Se agregaron scripts/kx_dual_file_rollback_fault_lab.ps1 y .github/workflows/kx-dual-rollback-fault-ci.yml en la rama experimental.

- GitHub Actions Windows PowerShell 5.1: PASS, run 43692746158, commit ac3d8647c7bf27516b1d02294c24e6b63ef95486.
- Se ensayaron solo fixtures: fallo tras primer reemplazo, fallo tras segundo reemplazo y recuperacion planificada de ambos.
- Cada ensayo recupero los dos hashes originales. No hubo intervencion en EC2, servicios, tareas, puertos, RDS ni control fisico.
- APROBADO EN EC2 (evidencia de consola del operador, 2026-11-15): EC2CopyLab completo sobre espejos NTFS con backups/candidatos reales. PASS para FAIL_AFTER_FIRST, FAIL_AFTER_SECOND y PLANNED_ROLLBACK; ambos hashes originales restaurados en los tres casos, hashes productivos Caddyfile y lanzador intactos, control fisico OFF. El informe privado se guarda en kx_dual_rollback_fault_lab_v1/dual_rollback_report.json. La ejecucion del servicio real sigue SIN probar.
- NO IMPLEMENTADO: watchdog independiente, rollback tras cierre abrupto del operador, coordinacion de reintentos y recuperacion real del HTTPS 443.

Este avance NO cambia NO-GO_PUBLICACION ni autoriza el cutover.
