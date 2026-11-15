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
