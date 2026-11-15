# K-X | Auditoria del paquete productivo V1 y correcciones V2 (2026-11-15)

**Estado de publicacion: NO-GO.** Este documento no autoriza reiniciar Caddy, activar K-V publico ni cambiar permisos de hardware.

## Evidencia confirmada por el operador en EC2

El operador ejecuto kx_prod_bundle_stage_only.ps1 y devolvio:

- PAQUETE CUTOVER REAL PREPARADO, NO ARMADO.
- COPIAS ORIGINALES/CANDIDATAS: PROTEGIDAS Y VERIFICADAS.
- CONTROLADOR Y RECUPERADOR: PRESENTES, BLOQUEADOS.
- HTTPS 443: SIN RESTART NI CAMBIOS.
- TAREAS PRODUCTIVAS: INTACTAS, SIN WATCHDOG REGISTRADO.

Paquete V1 instalado en C:\ProgramData\VehiculoIoT-KX-Installer\kx_https_cutover_bundle_v1_NOT_ARMED. **No modificar ni sobrescribir.** Es snapshot de preparacion, no un ejecutable aprobado para publicacion.

## Hallazgos bloqueantes de auditoria V1

1. **Colision PowerShell HOME:** V1 asigna script:Home que colisiona con la variable automatica de solo lectura HOME (no distingue mayusculas). Incluso la accion Review falla antes del try. V1 sigue bloqueado; no ejecutarlo.
2. **Crash en estado temporal:** la ruta fija transaction.json.next puede quedar tras un crash, bloqueando los intentos posteriores. V2 emplea temporales GUID atomicos y limpieza por escritura.
3. **Caddy sin registro de proceso:** V1 requiere run\caddy.json aun si el supervisor ya murio y el registro no existe. V2 permite ausencia solo cuando no hay Caddy ni escucha 443 desconocidos, y protege la identidad del proceso.
4. **Comprobacion de rollback insuficiente:** V1 se apoyaba en HTTP 200 y Task Running. V2 exige hashes originales, supervisor/hijo SYSTEM exactos, propietario unico del 443, y HTTPS/TLS GET 200.
5. **Estados terminales no idempotentes:** V1 rechazaba COMMITTED_VERIFIED / ROLLED_BACK_VERIFIED; V2 comprueba el estado terminal sin detener Caddy confirmado.
6. **Desbloqueo unilateral:** V1 podia habilitar el controlador con recuperador aun inoperativo. V2 valida que el recuperador compatible este expresamente habilitado antes de armar watchdog. Ambos permanecen bloqueados.
7. **Verificacion del candidato:** V2 agrega SHA256 de archivos candidatos, Caddy SYSTEM hijo y listener 443, Caddy admin 2019 no publico y K-V 9444 solo loopback.

## Artefactos V2 experimentales (NO COPIAR A PRODUCCION)

- scripts/kx_prod_cutover_controller_v2_LOCKED.ps1
- scripts/kx_prod_recoverer_v2_LOCKED.ps1
- .github/workflows/kx-prod-cutover-v2-locked-review-ci.yml

GitHub Actions Windows PowerShell 5.1 PASS: run 43698906454, commit 4d92a856d535a3109785985a8061655b2dd1f68a. Comprueba parser, barreras de v2, invocaciones reales de rechazo por procesos separados para Action Cutover y Action Recover, y conteo identico de tareas temporales. No modifica ningun servicio real.

**Limite:** estas son validaciones estaticas y de bloqueo; **no prueban** parada/reinicio ni rollback productivo.

## Puertas que faltan antes del cambio real

- Versionar V2 en paquete separado con hashes inmutables; no reutilizar V1.
- Validar casos de fallo relevantes de V2, en particular ausencia del registro de procesos, temporal .next huerfano, estados terminales y dueños de escucha.
- Revisar y ensayar el arbitraje de reintentos 999/PT1M y escenario de reinicio Windows, incluido AtStartup; aun no esta demostrado.
- Diseñar gate de doble habilitacion solo tras comprobar recuperacion bajo SYSTEM, deadline armado, identidad Caddy y preflight HTTPS.
- Documentar plan de contingencia operativa si el watchdog falla, con ventana deliberada y monitoreo de HTTPS legacy/K-V.
- Solo tras prueba y autorizacion de la ventana ejecutar la sustitucion real de los dos archivos. Esta transaccion nunca autoriza activar el hardware.

**Decision: V1 STAGED_LOCKED PASS; V2 REVIEW_CI_PASS; REAL_CUTOVER NO-GO.**

## Regresion especifica V2 y paquete nuevo (2026-11-15)

- GitHub Actions Windows PowerShell 5.1 run 43699515256 PASS, commit 8ab9a3529f5261691802b3287a6f0b7c4d188c2f, **42 aserciones**. El harness importa directamente las funciones de ambos scripts V2 mediante AST y ejecuta las transiciones contra archivos temporales y mocks de tareas, procesos y HTTPS.
- Casos PASS: temporales .next interrumpidos; registro Caddy ausente sin proceso vivo; bloqueos ante tarea Running sin identificacion, PID Caddy ajeno y propietario 443 ajeno; PREPARED intacto; COMMITTED_VERIFIED sano sin rollback y hash alterado falla cerrado; ROLLED_BACK_VERIFIED idempotente; PATCHING a mitad de dos archivos y ROLLBACK_IN_PROGRESS recuperados.
- **Alcance limitado**: no ejecuta Task Scheduler real, ni reinicia Caddy; valida funciones de V2 con comportamiento del SO simulado. No valida reboot Windows ni caida de RDP.
- Nuevo instalador `scripts/kx_prod_bundle_v2_stage_only.ps1` usa ruta separada `kx_https_cutover_bundle_v2_NOT_ARMED`; antes de copiar verifica que V1 este privado e inactivo. Usa hashes Git fijados de controlador y recuperador V2 y copias originales/candidatas inmutables.
- CI de sintaxis/AST del instalador V2 PASS run 43699654646, commit ded6ea5af7b834fdd006da3c20983175e83678fa. Comprueba ausencia de mutaciones de tareas en stage-only, rutas separadas y barreras LOCKED.
- **APROBADO EN EC2 (evidencia del operador)**: `kx_prod_bundle_v2_stage_only.ps1` termino con `PAQUETE V2 REVISADO PREPARADO, NO ARMADO`, copias SHA verificadas, controladores V2 presentes y bloqueados, HTTPS 443 y tareas productivas intactos, sin watchdog registrado. La V1 permanece tal cual. NO-GO_PUBLICACION no cambia.

## Estado del paquete V2 tras reconexion RDP (2026-11-15)

- El operador reporto reconexion de su sesion RDP y despues salida terminal de PASS de stage-only V2, incluido `LASTEXITCODE` sin throw.
- La desconexion por inactividad de RDP no se interpreta como reboot ni como recuperacion real del Caddy, y el script de staging no usa tareas activadas ni cambia 443.
- Siguiente comprobacion concreta: correr `-Action Review` de ambos ejecutables V2 ya instalados, despues de verificar SHA Git; solo consulta archivos protegidos, la tarea y el estado PREPARED.
- La publicacion permanece **NO-GO** aunque ambos Review terminen PASS. Ninguna tarea productiva debe deshabilitarse por esta comprobacion.
