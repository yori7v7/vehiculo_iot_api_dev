# Etapa 5.5-K-Z — contrato de tercera tarea Windows y reversión segura

**Estado: PRUEBA EN WINDOWS CI APROBADA; NO DESPLEGADA.** Este archivo describe lo probado, sin confundir una tarea ficticia con un servicio real de producción. Fecha: 13/11/2026.

**Entrega académica:** la única URL del frontend se conserva en https://yori7v7.github.io/control-iot-u4/ y su repositorio es https://github.com/yori7v7/control-iot-u4. El código CONTROL/MONITOREO de `main` y las dos tareas originales de EC2 no se alteraron.

## Qué se comprobó

- `tests/kz_windows_task_lifecycle_ci.ps1` crea, en un Windows efímero de GitHub Actions, una tarea **ficticia** de nombre aleatorio `KZ-Virtual-CI-...`, con principal `NT AUTHORITY\LOCAL SERVICE` (SID `S-1-5-19`) y privilegios limitados.
- La tarea usa una **acción de lectura del repositorio**, NO arranca FastAPI ni el sidecar. Se registra **sin triggers** y luego se deshabilita explícitamente. Nadie puede convertir este ensayo en un despliegue del vehículo ni probarlo mediante el enlace público.
- La carpeta temporal privada tiene herencia ACL desactivada. Se permite acceso solo al usuario técnico del runner, SYSTEM, Administradores y LocalService. Se verifica que Everyone, Authenticated Users y Users no tengan escritura.
- Se escribe un manifiesto **sin secretos**, con hashes SHA-256 del Caddyfile original y el candidato, y `virtual_only=true`. No se crea API key ni contraseña de AWS.
- Se comprueba el SHA-256 de `deploy/windows/Caddyfile`, `install.ps1`, `run_api.ps1`, `run_caddy.ps1` y `app/main.py` ANTES y DESPUÉS de la prueba.
- Se elimina **solo la tarea aleatoria de CI** con `Unregister-ScheduledTask` y la carpeta temporal de prueba; si ocurre una excepción, un `finally` intenta ejecutar esa misma limpieza. No se tocan `VehiculoIoT-Caddy` ni `VehiculoIoT-FastAPI`.

**Evidencia:** GitHub Actions [43406064687](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43406064687), **SUCCESS**, salida `[K-Z] RESULTADO: 26 verificaciones; LocalService/ACL/tarea/reversion CI`. El ensayo K-Y anterior [43401467467](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43401467467) probó **18 comprobaciones** de arranque/parada/reinicio del sidecar real en 9444 mientras un *servidor HTTP sintético* en 8000 permanecía encendido. Son pruebas complementarias, **no** la misma prueba de tareas.

## Preflight de solo lectura

Se agregó `deploy/staging/kw/kz_installation_plan_readonly.ps1` con modos `VerifyRepository` y `Plan`. Es intencional que **no tenga parámetros `-Install`, `-Apply` ni `-Deploy`**.

En una copia de trabajo de la rama experimental, sin encender AWS, es posible ejecutar:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ".\deploy\staging\kw\kz_installation_plan_readonly.ps1" -Mode VerifyRepository
```

Verifica de forma estática que el Caddyfile original solo enrute al puerto 8000, el candidato contemple `8000` y `9444`, la IP ficticia de CI `8.8.8.8` no aparezca en el candidato y el backend de tickets se identifique como virtual. Solo imprime mensajes de validación; código `2` indica NO-GO.

`-Mode Plan` imprime un diseño para una futura tarea `VehiculoIoT-Admission-Virtual`, **pero no la crea**. No lee `.env`, no consulta AWS, no abre puertos, no instala paquetes ni modifica Task Scheduler.

## Limitaciones: aún no está lista la instalación real

1. **La acción real de la nueva tarea falta.** El lanzador K-Y está blindado para usarse **solo dentro de Windows GitHub Actions**, por lo que no funcionaría en EC2; esto es intencional. Se debe diseñar un lanzador aprobado de `staging` con su propio arranque seguro antes de registrar tareas de producción.
2. La prueba K-Z verifica que LocalService puede ser asignado a una tarea, pero **no ejecutó el proceso FastAPI con identidad LocalService** ni certifica acceso de lectura a las dependencias Python o escritura a SQLite en el sistema EC2 real.
3. Falta decidir una carpeta privada de `ProgramData` con ACL, proteger dos secretos distintos (proxy y administrador), validar identidad y límites, definir persistencia/backup y auditar el puerto local 9444.
4. La configuración de Caddy del servidor sigue enviando tráfico al backend original 8000. El candidato `deploy/staging/kw/Caddyfile.candidate_NOT_DEPLOY` **NO** se ha instalado, auditado ni ensayado en Windows EC2.
5. La página original de GitHub Pages sigue sin habilitar la admisión pública. Los tickets K-V `canDrive=false` no autorizan joystick, DEMO o movimientos.
6. **El rollback de K-Z solo demuestra que se puede retirar la tarea ficticia en CI.** No demuestra que Caddy pueda recargarse/recuperarse tras un despliegue defectuoso, ni que EC2 pueda recuperarse después de reiniciar servicios. Un rollback real requiere copia privada del Caddyfile activo, validación de configuración y ensayo supervisado.
7. Antes de control físico: autoridad única de comandos y pruebas de STOP autónomo, desconexión, watchdog e interlocks del vehículo. No tratar un `HTTP 503` como prueba de parada mecánica.

## Criterio de GO siguiente

Continuar con un **paquete de instalación independiente de la tercera tarea** solamente cuando pueda ejecutarse con un usuario dedicado de mínimos privilegios, mantener secret storage y SQLite bajo ACL válidas, y contar con un rollback del proxy probado. Antes de habilitar AWS/EC2 o abrir servicios reales, confirmar una ventana de prueba con el usuario. **Nunca habilitar batería, RDS o credenciales del vehículo para el servicio virtual.**

## Componentes nuevos

- `deploy/staging/kw/kz_installation_plan_readonly.ps1`: plan de la tercera tarea, solo lectura.
- `tests/kz_windows_task_lifecycle_ci.ps1`: tarea temporal real, LocalService/ACL, validación y reversión.
- `tests/test_kz_windows_task_plan_contract.py`: regresiones estáticas.
- `.github/workflows/kz-windows-task-ci.yml`: Windows GitHub Actions, no EC2.

**Resultado: K-Z validó el procedimiento de registro/eliminación de una tercera tarea aislada. NO existe una instalación de K-V funcionando en EC2, y la autorización física sigue completamente inhabilitada.**
