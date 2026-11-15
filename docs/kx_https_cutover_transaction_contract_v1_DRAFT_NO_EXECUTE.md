# K-X — contrato de transaccion HTTPS y recuperacion v1 (DRAFT / NO EJECUTAR)

**Estado actual: GO_LAB / NO-GO_PUBLICACION.** No es un script ni un permiso para reiniciar Caddy. Su alcance es publicar solamente K-V virtual tras el proxy existente, conservando REST/WSS legado y sin habilitar el control fisico.

## Evidencia confirmada a 2026-11-15

- Identidad del supervisor y Caddy hijo bajo SYSTEM: PID, creation_ticks, ruta ejecutable, padre/hijo y unico propietario de 443; tarea VehiculoIoT-Caddy tiene 999 reintentos cada PT1M.
- Reemplazo de ambos archivos y rollback en copias NTFS del EC2: 3 escenarios aprobados.
- Recuperacion desde otro proceso en copias EC2 y caso de commit sin falso rollback: aprobados.
- Recuperacion mediante tareas SYSTEM temporales en EC2: 3 escenarios aprobados, tareas laboratorio eliminadas.
- Tarea SYSTEM con activacion automatica por horario en EC2, fallo tras segundo reemplazo: aprobada; tareas laboratorio eliminadas. CI homologado: run 43694395316.
- Caddy candidato con rutas virtuales y legado ya ensayado bajo SYSTEM en laboratorio local. **No se ha ensayado el cutover real ni la restauracion real de 443.**

## Cambios productivos permitidos exclusivamente dentro de ventana autorizada

Dos archivos de contenido: C:\ProgramData\VehiculoIoT\Caddyfile y C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1. Los backups exactos viven en el instalador privado y se verifican contra SHA256. No alterar deploy/windows/common.ps1, tareas FastAPI/K-V, credenciales, firewall, RDS, ESP ni motores.

## Arquitectura obligatoria del par integrado

**Ejecutor transaccional** y **recuperador SYSTEM** son archivos independientes, preinstalados en carpeta privada SYSTEM/Administradores con hashes conocidos. El recuperador no necesita que el ejecutor, RDP, K-V o Internet esten disponibles. Nunca lee ni imprime secretos de K-V, API key o tokens salvo que el lanzador candidato lea bajo SYSTEM su proof privado solamente en memoria.

**Bloqueo:** los procesos pueden estar en distintas sesiones de Windows (RDP y session 0 SYSTEM). Un mutex Local\ no coordina entre sesiones; implementar lock NTFS exclusivo mediante FileStream con FileShare.None (o mutex Global\ con ACL explicitamente restringidas), con timeout y liberacion al morir el proceso. Ningun reemplazo ni rollback ocurre fuera del lock.

**Recuperacion duradera:** registrar una tarea bajo SYSTEM con disparo horario antes de cualquier mutacion, StartWhenAvailable y trigger de arranque de Windows, con deadline concreto. Probar aparte su comportamiento ante reboot antes de afirmarlo. El watchdog es temporal y se desarma solo tras salud comprobada. Nunca fiarse de un simple archivo 'committed.flag' sin verificar integridad/ACL y transicion autorizada del estado.

**Estados durables:** PREPARED -> ARMED -> QUIESCING -> PATCHING -> STARTING -> VERIFYING -> COMMITTED_VERIFIED. Si falla o vence el deadline desde ARMED: ROLLBACK_IN_PROGRESS -> ROLLED_BACK_VERIFIED, o INCIDENT_MANUAL cuando no es seguro continuar. Los estados se actualizan mediante reemplazo atomico de un unico registro protegido, con transaction_id no predecible y hashes de archivos.

**Reintentos reales:** antes de apagar el Caddy original, deshabilitar temporalmente VehiculoIoT-Caddy para impedir carrera con sus 999 reintentos. Luego detener la tarea y solamente su supervisor/hijo cuyos PID, creation_ticks, executable_path, SID SYSTEM y relacion padre-hijo hayan sido comprobados. Nunca usar taskkill por nombre. Ante otro propietario de 443, NO-GO; no matar procesos desconocidos.

**Reemplazo:** cuando Caddy original este inactivo y la recuperacion armada, IO.File.Replace del Caddyfile y luego launcher; es atomico por archivo y NO atomico en conjunto. Verificar backups, hashes, ACL NTFS, ausencia de reparse points, common.ps1 intacto y candidato Caddy validado. Si falla cualquiera, recuperar ambos antes de reanudar.

**Rearranque y validacion:** rehabilitar la MISMA tarea VehiculoIoT-Caddy bajo SYSTEM y verificar un unico Caddy en 443. Comprobar TLS/certificado y hostname, GET legacy /health y /openapi.json, rutas K-V con 200/401/403 y Origin invalido, no-store, ninguna exposicion directa de 9444/9481/admin 2019, estado virtual true/control fisico false, sin tickets y sin proof literal almacenado. No ejecutar acciones POST de control. La tarea Running no reemplaza una comprobacion de listener y HTTP.

**Recuperador:** ante fallo/timeout, obtener lock transaccional, deshabilitar primero tarea Caddy, identificar procesos estrictamente, restaurar los dos originales desde backups verificados (nunca config privada antigua), reactivar la misma tarea, verificar 443 TLS y legado y ausencia de K-V publico. Si algo no coincide, marcar INCIDENT_MANUAL, NO-GO, y dejar diagnostico redactado sin secretos. El watchdog no debe intentar actuacion concurrente con el ejecutor.

**Post-commit:** solo guardar COMMITTED_VERIFIED tras salud real positiva, comprobar que watchdog lo reconoce y que se ha desarmado/eliminado. Mantener backup, hash, estado y evidencia privados, sin secretos.

## Cortes de seguridad y permisos

- No cortar HTTPS hasta tener recuperador registrado y comprobado bajo SYSTEM.
- No actuar si la sesion RDP, respaldos, integridad, identidad, ACL, tareas o salud previa son incorrectas.
- Requiere autorizacion expresa del operador para una posible interrupcion de HTTPS 443 y ventana disponible; NO implica permiso para activar hardware.
- La recuperacion en espejos y el auto-trigger de laboratorio NO demuestran aun recuperacion tras cierre de RDP/reboot ni control de reintentos reales.

## Siguiente entrega concreta

Implementar y revisar **un unico par integrado** de ejecutor y recuperador basados en este contrato, con una simulacion de extremo a extremo sobre servicio ficticio; no repetir escenarios independientes ya aprobados. Tras validar el conjunto, solicitar autorizacion para la ventana real. Mantener NO-GO_PUBLICACION hasta entonces.

## 2026-11-15: par integrado de ejecucion y recuperacion -- CI WINDOWS APROBADO

- scripts/kx_integrated_operator_LAB_ONLY.ps1: ejecutor con estados protegidos, lock FileStream/FileShare.None entre sesiones, servicio ficticio SYSTEM con 999 reintentos/PT1M, tarea recuperadora prearmada y dos escenarios de extremo a extremo.
- scripts/kx_integrated_recoverer_LAB_ONLY.ps1: recuperacion independiente por tarea SYSTEM, validacion de hashes y carpeta privada, restaura ambos archivos ficticios y comprueba salud del servicio original; no revierte un commit saludable.
- .github/workflows/kx-integrated-cutover-lab-ci.yml: PASS run 43696193313, commit 12535c9eab6fc65db9353c99380135433545c29e.
- CI CRASH_AFTER_SECOND: ejecucion interrumpida de forma intencional, watchdog auto bajo SYSTEM, restauracion SHA256 doble, servicio fake ORIGINAL saludable, estado durable ROLLED_BACK_VERIFIED.
- CI COMMIT_OK: servicio fake CANDIDATE saludable, watchdog sin falso rollback, estado durable COMMITTED_VERIFIED, tareas de laboratorio eliminadas.
- APROBADO EN EC2 (evidencia del operador 2026-11-15): ejecucion de `kx_integrated_operator_LAB_ONLY.ps1 -Mode EC2CopyLab`, resultado completo **TRANSACCION INTEGRADA CON SERVICIO FICTICIO APROBADA**, `CRASH_AFTER_SECOND` restaura dos archivos y recupera servicio, `COMMIT_OK` conserva candidato sano; tareas LAB eliminadas y Caddy/tareas reales intactos.
- El par integrado ES LABORATORIO SOLAMENTE. No ejecuta cutover 443 ni rollback de servicio productivo; reboot real, RDP, TLS/ACME y procesos productivos pendientes de ensayo autorizado.

Estado GO_INTEGRACION_EC2 / NO-GO_PUBLICACION. Los ensayos aislados y el end-to-end LAB han concluido.

## Gate final read-only antes de preparar cutover

- Script `scripts/kx_release_integrated_inventory_readonly.ps1` creado en rama experimental y CI static Windows PowerShell 5.1 PASS (run 43696877424, commit fd65cfdb99878abd55128f1e4e21ebec61d9898e).
- Solo consulta hashes, manifests, report de integracion EC2, ausencia de tareas LAB residuales, tareas reales Running, PID/creation_ticks/SYSTEM de supervisor/hijo, propietario de 443, 999/PT1M y aislamiento 9444/8000.
- Aun NO ejecutado en EC2 del operador. No lee secretos ni realiza HTTP, reinicios, escrituras o registro de tareas. Un PASS de este gate NO autoriza cutover.
- PENDIENTE: implementar mecanismo de intervencion y recuperacion para **tareas y servicio reales**, validarlo en seco y solicitar permiso expreso para ventana HTTPS. No existe autorizacion actual para tocar 443.

## 2026-11-15: NO-GO del inventario productivo read-only; correccion defensiva

- El operador ejecuto kx_release_integrated_inventory_readonly.ps1 commit fd65cfdb99878abd55128f1e4e21ebec61d9898e y obtuvo NO-GO en TASK_AND_PROCESS, tipo PropertyNotFoundException. No hubo cambios productivos.
- Causa exacta aun NO CONFIRMADA: la salida compartida no incluye el ultimo OK del inventario ni la linea; en el codigo se detectaron expresiones no robustas para PowerShell StrictMode (consulta de Actions[0] y retorno escalar de funciones de listener).
- Parche de script en commit ec809956ec1a8405f91771de4430e87ba61bdf77 (blob d056482c3bafb08786b0aac45ae56f8ca2c2fe3d). Refactor de propiedades task/arrays de puertos y diagnostico sanitizado PASO/LINEA/TIPO. CI PS5.1 parser y prohibicion de verbos mutadores PASS run 43697172461.
- El parche NO ha sido ejecutado en la EC2 del operador. El resultado NO-GO sigue vigente hasta verificar inventario corregido; aun con PASS, publicacion permanece NO-GO hasta contar con recuperador productivo real, comprobaciones HTTP y autorizacion.

## 2026-11-15: inventario integrado corregido aprobado en EC2

- Evidencia del operador: kx_release_integrated_inventory_readonly.ps1 revision ec809956ec1a8405f91771de4430e87ba61bdf77 finalizo con RESULTADO: K-X INVENTARIO INTEGRADO READ-ONLY APROBADO.
- Confirmado por salida: evidencia del laboratorio integrado en EC2; sin tareas temporales; Caddy SYSTEM y FastAPI/K-V intactos; reintentos de tarea Caddy 999/PT1M; ninguna escritura/restart de tareas, Caddy, red, AWS, RDS o motores.
- La falla previa del inventario (PropertyNotFoundException en TASK_AND_PROCESS) quedo superada al ejecutar la revision defensiva. No inferir de ello un cambio de estado productivo.
- Estado actual: GO_LAB_EC2 / GO_INVENTARIO_READONLY; sigue NO-GO_PUBLICACION hasta tener paquete de ejecutor/recuperador productivos realmente implementado, comprobado y ventana de corte deliberada.

## Resultado de auditoria corregida del servidor (2026-11-15)

- El operador confirmo PASS de kx_release_integrated_inventory_readonly.ps1 revision ec809956ec1a8405f91771de4430e87ba61bdf77.
- Evidencia en EC2: laboratorio integrado sin tareas temporales, Caddy/launcher original y tareas FastAPI/K-V sin cambios, reintentos Caddy 999/PT1M, procesos SYSTEM y loopback comprobados; ninguna accion mutadora.
- El NO-GO previo por PropertyNotFoundException en TASK_AND_PROCESS era una falla de compatibilidad del script auditado. No se publico K-V ni se modifico HTTPS.
- Ahora se prepara un paquete protegido fuera del servicio para el cutover real y su recuperador, que se mantendra desactivado hasta la ventana deliberada.
