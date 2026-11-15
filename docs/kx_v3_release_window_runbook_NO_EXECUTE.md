# K-X HTTPS V3 — Ventana final de publicacion y respuesta ante incidentes
ESTADO: BORRADOR / **NO EJECUTAR HASTA STAGING V3 + REVIEW V3 EN EC2 APROBADOS**.

## Justificacion del plan

El Caddyfile candidato usa un placeholder runtime env.KX_STAGING_PROXY_PROOF. El proceso Caddy existente fue iniciado con el launcher legado y sin ese entorno privado: una recarga "sin parada" no garantiza que el proxy autentique a K-V. No cambiar el placeholder a secreto literal: comprometeria la prohibicion de secretos en Caddyfile/autosave. El plan conserva parada/reinicio acotado de la tarea Caddy original bajo SYSTEM con rollback SYSTEM independiente.

## Evidencias actuales

- V2 stage y V2 Review aprobados en EC2 por el operador, sin watchdog ni corte.
- Ensayo integrado de fallos y tareas Windows SYSTEM, en laboratorio EC2, aprobado.
- Regresion V2 de funciones reales con mocks en Windows GitHub Actions: 42 aserciones PASS, run 43699515256.
- V3 candidata preparada en fuentes; pruebas static, rechazo de acciones no autorizadas y regresion de funciones sobre fixtures PASS run 43701005361 (commit 4e9a4725dc0f4609a6e9c88a22e0ccf9f636904b).
- **V3 aun NO se instalo ni reviso en EC2. HTTPS 443 sigue con Caddy original.**

## Contrato de seguridad V3

- Bundle propio sin reutilizar V1 o V2: C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v3_RELEASE_READY
- Dos archivos productivos previstos: C:\ProgramData\VehiculoIoT\Caddyfile y C:\vehiculo_iot_api_dev\deploy\windows\run_caddy.ps1. Nunca cambiar common.ps1 ni tareas FastAPI/K-V.
- Controller: por defecto -Action Review. Cutover requiere -Action Cutover -AuthorizeRealCutover, verificacion elevada y hashes de manifiesto. No autoiniciar despues de stage.
- Recuperador: -Action Recover solo ejecutable bajo SID SYSTEM, con tarea separada. Protegido por hash del propio codigo/respaldos y lock FileShare.None.
- Antes de tocar archivos, registrar tarea independiente SYSTEM con triggers Once/AtStartup, RestartCount 3/RestartInterval 1 min; probar entrada exacta bajo SYSTEM cuando el estado es PREPARED y comprobar exit 0; luego marcar ARMED. Si falla la prueba no se modifica Caddy.
- Deshabilitar primero tarea Caddy para impedir los 999 reintentos/PT1M durante intervencion. Parar exclusivamente su supervisor/hijo SYSTEM identificados. Nunca finalizar procesos por nombre ni tocar puertos ajenos.
- Reemplazar y comprobar ambos SHA256, rehabilitar/iniciar tarea Caddy original bajo SYSTEM, verificar GET TLS /health y /openapi.json mas K-V 200/401/403, no-store, estado simulado, ausencia de tickets, listener 443 de Caddy verificado, 8000/9444 aislados.
- Si la ejecucion falla antes del commit, el recuperador intenta restaurar ambos respaldos originales y deja evidencia ROLLED_BACK_VERIFIED o NO-GO; no prometer tiempos de recuperacion fijos ni restauracion infalible.
- Si ya se guardo COMMITTED_VERIFIED, no forzar rollback por un mero fallo de limpieza del watchdog: inspeccion y respuesta operatoria.
- Tras commit completo, verificar task original Running, propietario 443 y GET TLS; entonces watchdog desarmado y sin tarea residual.

## Antes de ordenar el corte real

1. No hay solicitudes virtuales pendientes ni operadores controlando el sistema. Hardware/bateria no habilitados, control_fisico=false, no tocar RDS ni firewall.
2. Paquete V3 staged + -Action Review de ambos ejecutables PASSED y hashes de codigo V3 verificados. V1 y V2 sin cambios.
3. Acceso administrativo/RDP estable, ventana breve de posible interrupcion del portal, plan para volver a conectar si RDP se cae, usuario presente frente al servidor.
4. Verificar endpoint publico TLS legado 200 y runtime loopback antes de cambiar. Si falta alguna comprobacion, NO-GO.
5. Una sola ejecucion deliberada del controlador V3 con -Action Cutover -AuthorizeRealCutover. Nunca relanzar si falta conexion durante la transaccion o se obtiene NO-GO; inspeccionar primero estado/tareas/archivos.

## Si aparece NO-GO o se pierde RDP

- No relanzar el controlador. No ejecutar taskkill, Stop-Service ni editar manualmente Caddyfile/launcher.
- Reconectar EC2. Inspeccionar primero transaction.json.phase, task watchdog y original, listener 443 y dos hashes; no copiar tokens ni secretos a chats/logs.
- Si ROLLED_BACK_VERIFIED: comprobar /health y /openapi.json publicos, que K-V no se publico y que no hay watchdog residual.
- Si COMMITTED_VERIFIED: comprobar rutas nuevas y legado, procesos/443; un fallo de limpieza de la tarea es incidente post-commit, NO rollback a ciegas.
- Si ARMED/QUIESCING/PATCHING/STARTING/VERIFYING/ROLLBACK_IN_PROGRESS: el recuperador SYSTEM debe asumir el rollback automatico; si no ocurre, incidente manual y diagnostico de tarea SYSTEM. No prometer que reinicios de Windows o cierre de RDP ya estan certificados.
- Si INCIDENT_MANUAL o hash distinto de ambos originales/candidatos: detener intervencion; no reemplazar ni matar procesos ajenos.
- Un reboot Windows no fue ensayado en el servicio productivo. El trigger AtStartup existe como defensa adicional, no prueba de funcionamiento garantizado.

## Ultima decision registrada

GO_CI_V3_SOLAMENTE / **NO-GO_PUBLICACION** hasta que stage + Review V3 terminen PASS en EC2 y el operador ejecute expresamente el comando de ventana. La autorizacion general del usuario para continuar no equivale a haber realizado el cambio de HTTPS.


## 2026-11-15: V3 PREPARED y ambos Review PASS en EC2

- Evidencia del operador: `RESULTADO: K-X V3 PREPARADA Y REVISADA` con `CONTROLADOR V3: REVIEW PASS`, `RECUPERADOR V3: REVIEW PASS`, `TRANSACCION: PREPARED`, `WATCHDOG: NO ARMADO` y `HTTPS 443: NO MODIFICADO`.
- La prueba en EC2 de las dos entradas `-Action Review` fue exitosa. No equivale a haber ejecutado `-Action Cutover` ni `-Action Recover`.
- Paquete V3 instalado bajo `C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v3_RELEASE_READY`; V1 y V2 quedan separados e intactos.
- Siguiente hito: una unica ventana HTTPS real con comprobacion de preflight en vivo, autorizacion explicita de comando y recovery independiente bajo SYSTEM. Si hay NO-GO no relanzar ni reiniciar manualmente hasta inspeccionar estado y tareas.
- Estado `GO_STAGE_AND_REVIEW_V3_EC2 / NO-GO_443_UNTIL_EXECUTION`.
