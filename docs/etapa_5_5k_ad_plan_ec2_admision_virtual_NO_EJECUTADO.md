# 5.5-K-AD — Plan de inspección EC2 y primera admisión virtual (NO EJECUTADO)

**Estado al 13/11/2026:** PREPARACIÓN DOCUMENTAL Y DOS CONTROLES DE SEGURIDAD VERIFICADOS EN WINDOWS CI. Solo se añade este plan a la rama experimental del PR #5. **No se ha encendido EC2, no se ha intervenido Caddy, no se ha creado servicio, no se ha probado con ESP ni se ha publicado admisión alguna.** `main`, el frontend y GitHub Pages siguen fuera del alcance de esta etapa.

## Objetivo acotado

Verificar de manera incremental la posibilidad de convivir con el backend FastAPI legacy en `8000` y un sidecar **exclusivamente virtual** en `127.0.0.1:9444`. La primera meta con EC2 no es habilitar órdenes al vehículo: consiste en obtener inventario de solo lectura, tomar una decisión GO/NO-GO documentada y, en una ventana posterior, validar admisión `canDrive=false` con rollback comprobado.

## Lo que SÍ se puede avanzar sin laptop, ESP ni AWS

- Auditar en GitHub el plan K-AB, el preflight K-AC, las pruebas del candidato Caddy y los resultados CI. La ejecución remota de Actions usa runners efímeros y no representa inspección de la instancia EC2 real.
- Revisar que el pipeline comprueba rechazo ante acceso no autorizado, inyección de cabeceras, caída del sidecar y recuperación del servicio legacy sintético.
- Preparar criterios de aceptación y una plantilla de evidencia **sin contraseñas, tokens, archivos con secretos, IP privadas ni contenido íntegro del Caddyfile persistente**.
- Mantener el PR en borrador sin fusionar ni cambiar repositorios productivos.

## Avance offline confirmado: control fail-closed de listeners

**Windows CI aprobada (13/11/2026):** [K-AD, workflow de preflight Windows run 43435119393](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43435119393). El paso `K-AD matriz fail-closed de listeners (sin sockets)` concluyó correctamente: 11/11 escenarios sintéticos ejecutados en un runner Windows, **sin consultar la red real ni tocar EC2**. La regresión general del backend del mismo commit también concluyó con éxito: [run 43435127636](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43435127636).

Se corrigió un falso positivo previo: el preflight podía informar GO sobre los puertos si no había ningún listener porque iteraba solo los resultados existentes. Ahora:
- **NO-GO** si el puerto 8000 del backend original no tiene listener.
- **NO-GO** si cualquier listener de 8000 no pertenece a `127.0.0.1` o `::1`.
- **NO-GO** si 9444 ya está ocupado, incluso por un servicio local: esta inspección es deliberadamente **preinstalación**, no una monitorización de un sidecar ya autorizado.
- El control es de solo lectura y devuelve códigos de decisión; **NO comprueba salud HTTP del backend, identidad del proceso, ACL del listener ni seguridad del firewall externo**.

Archivos: `deploy/staging/kw/kad_listener_policy.ps1` (función pura), `tests/kad_listener_policy_ci.ps1` (11 casos), `deploy/staging/kw/kac_ec2_preflight_READONLY.ps1` (integración Server) y `.github/workflows/kac-windows-readonly-ci.yml`. Este avance no autoriza encendido ni despliegue.

## Avance offline confirmado: identidad de tareas y propietarios de puertos

**CI Windows aprobada:** [ejecución 43436362437](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43436362437), paso `K-AD verificación de propiedad de procesos (sin procesos del host)`. Resultado: **17/17 casos sintéticos aprobados** (28/28 al contar la matriz anterior de 11 puertos). La regresión general previa de backend, correspondiente a ese código de integración, también resultó correcta: [run 43436370510](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43436370510).

El script `-Mode Server` **ahora exige** que las dos tareas originales estén en estado `Running`, que `deployment.json` identifique rutas de binarios esperadas (Python y Caddy), que ProgramData legacy no permita escritura a usuarios comunes y que existan registros de ejecución `run/api.json` y `run/caddy.json`. Compara, sin publicar los valores, **PID, fecha de creación e imagen del proceso** vivo con los registros privados y el `OwningProcess` de todos los sockets de FastAPI `8000` y HTTPS Caddy `443`. Una ausencia, discrepancia o propietario adicional produce **NO-GO**. Una ruta de estado fuera de ProgramData también se rechaza inmediatamente.

La política de identidad `deploy/staging/kw/kad_process_policy.ps1` es pura y no consulta procesos; sus 17 escenarios en `tests/kad_process_policy_ci.ps1` usan solamente objetos falsos. El preflight `deploy/staging/kw/kac_ec2_preflight_READONLY.ps1` sí consulta procesos reales, **pero solo cuando un operador ejecute voluntariamente `-Mode Server` en Windows**. No se ejecutó contra EC2. `tests/test_kad_process_preflight_contract.py` impide por regresión retirar comprobaciones cruciales o introducir comandos de escritura.

**Limitaciones:** verificar identidad de proceso no equivale a probar respuesta HTTP, estado real de TLS o autorización física. Si el host usa un proxy distinto en `443`, cambia la instalación o faltan registros tras un reinicio, la política actual devolverá **NO-GO** y se requerirá inspección humana del despliegue; no modificar automáticamente la política para aceptar cualquier proceso. Se mantienen pendientes inventario de firewall, Security Groups, certificados, credenciales y rollback real de Caddy.

## Puertas de decisión, en orden

### A. Inventario EC2 (solo en una futura ventana expresamente autorizada)

1. Confirmar encendido autorizado de EC2, sin iniciar RDS; batería RC desconectada y ESP innecesaria.
2. Guardar por un canal privado de trabajo una copia/restauración verificable del Caddyfile **persistente de Windows**, distinto del template del repositorio. No adjuntarlo al repositorio.
3. En una copia actualizada de la rama experimental, revisar el script antes de ejecutarlo. Ejecutar solo el modo de lectura `-Mode Server` de `deploy/staging/kw/kac_ec2_preflight_READONLY.ps1`. Ante NO-GO/salida 2, **detener la etapa**; no ejecutar instalaciones, reinicios ni correcciones automáticas.
4. Inspeccionar las tareas existentes `VehiculoIoT-FastAPI` y `VehiculoIoT-Caddy`, identidad, ACL, listeners, Security Groups y Firewall; confirmar que no existe acceso externo a `9444`.
5. Verificar el servicio original `8000` y sus dependencias con RDS apagada, únicamente mediante solicitudes de lectura sin provocar comandos de actuación.
6. Registrar únicamente resultados saneados: fecha, rama/SHA, comando, código de salida, GO/NO-GO y observaciones, **nunca valores de secretos**.

### B. Antes de crear o habilitar el sidecar (trabajo posterior, no autorizado por este documento)

- Aprobar identidad dedicada de Windows y permisos mínimos; no utilizar SYSTEM/LocalService/NetworkService para saltar la restricción de K-AB.
- Definir almacenamiento seguro para secretos de proxy y administrador, distintos entre sí. No pasar secretos por argumentos, logs, GitHub Pages, archivos del repositorio ni variables expuestas a usuarios.
- Acordar procedimiento probado de backup/restore del Caddyfile persistente y rollback de tareas, certificados y puerto. El rollback de contenedor Linux K-AC **no prueba** un rollback en Windows.
- Revalidar FastAPI/CONTROL/MONITOREO y WSS originales; confirmar que un fallo de sidecar no ocasiona regresión ni expone un endpoint motor.
- Mantener la admisión `canDrive=false` aun si HTTPS, autenticación y turnos virtuales funcionan.

### C. Requisitos independientes antes de cualquier operación física

Arbitraje **único** entre Swagger, joystick y DEMO; inhibición eléctrica por defecto, STOP seguro real y prioritario, watchdog, desconexión, expiración/revocación y supervisión humana. **Ninguna prueba virtual ni estado 200/101 equivale a parada mecánica comprobada.** Las pruebas físicas deberán hacerse únicamente con laptop, ESP, vehículo, entorno seguro y autorización explícita.

## Matriz de evidencia (pendiente, no rellenar hasta observar resultados)

| Prueba | Entorno requerido | Resultado |
| --- | --- | --- |
| K-AC preflight Repository | GitHub CI / Windows local | Preexistente; consultar Actions y SHA exacto |
| K-AC TLS/fallo/rollback sintético | GitHub Actions, runner efímero | Preexistente; no extrapolar a EC2 |
| K-AD políticas de puertos y propietario de proceso | Windows CI con objetos simulados | **28/28 aprobadas**, no son prueba de EC2 |
| K-AD preflight Server | EC2 Windows real | **NO EJECUTADO** |
| Caddyfile persistente + copia restaurable | EC2 Windows real | **NO VERIFICADO** |
| Identidad/ACL y secretos del sidecar | EC2 Windows real | **NO CONFIGURADO/NO VERIFICADO** |
| Coexistencia real 8000/9444 | EC2 Windows real | **NO EJECUTADO** |
| Admisión virtual externa canDrive=false | EC2 Windows real + cliente remoto | **NO EJECUTADO** |
| Movimiento / STOP físico | Equipo físico completo | **FUERA DE ALCANCE DE K-AD** |

## Regla de salida

**Sin evidencia real y saneada de los puntos A, el estado es NO-GO para desplegar.** Mantener `main`, Pages y servicio legacy sin cambios. Este archivo es una planificación y NO certifica que haya pruebas nuevas aprobadas.

Referencias: `docs/etapa_5_5k_ac_preflight_ec2_y_rollback_caddy.md`, `docs/etapa_5_5k_ab_staging_windows_candidato.md`, `deploy/staging/kw/kac_ec2_preflight_READONLY.ps1` y `deploy/staging/kw/Caddyfile.candidate_NOT_DEPLOY`.
