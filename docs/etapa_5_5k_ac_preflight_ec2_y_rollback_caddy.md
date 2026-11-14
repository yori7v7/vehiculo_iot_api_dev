# 5.5-K-AC — Preflight EC2 de solo lectura, convivencia y rollback Caddy en CI

**Estado: K-AC PREPARADO EN RAMA EXPERIMENTAL. NO DESPLEGADO EN EC2.** Fecha de corte: 13/11/2026. El frontend académico permanece publicado en https://yori7v7.github.io/control-iot-u4/ y `main` no se modificó.

## Qué aporta frente a K-AB

K-AB había demostrado que el lanzador de staging virtual exige una identidad de servicio y una habilitación explícita en una tarea de Windows del runner. K-AC aborda el siguiente riesgo: **el estado persistente de Caddy en EC2 y el retorno al backend original**. Aunque `deploy/windows/Caddyfile` es una plantilla, el proceso real de Caddy carga `%ProgramData%\VehiculoIoT\Caddyfile`. No se debe reemplazar este último por suponer que ambos archivos son iguales.

### Componente 1: inspección EC2 sin escrituras

`deploy/staging/kw/kac_ec2_preflight_READONLY.ps1` tiene dos modos:

- `Repository`: únicamente comprueba el Caddyfile original (puerto 8000), el candidato (8000+9444), la identidad del cliente `{remote_host}`, la referencia externa `{$KW_PROXY_TOKEN}` y la barrera de identidad/activación de K-AB. No lee secretos ni requiere EC2.
- `Server`: diseñado para usarse **solo después de autorizar el encendido de EC2**; lee en memoria `deployment.json` y el `Caddyfile` realmente persistentes, las identidades/acciones de `VehiculoIoT-FastAPI` y `VehiculoIoT-Caddy`, los permisos del checkout y del binario Python, y los listeners 8000/9444. Si falta el estado, hay un listener público o la configuración no coincide, **devuelve código 2/NO-GO**. No instala, habilita, detiene, registra ni recarga procesos. No imprime contenido de credenciales ni configuración privada.

Comando permitido **ahora, solo para una copia local de la rama experimental**, sin AWS:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ".\deploy\staging\kw\kac_ec2_preflight_READONLY.ps1" -Mode Repository
```

En una ventana de inspección autorizada, prepara una **copia separada de auditoría** de la rama experimental en una carpeta de acceso administrativo. Verifica que el HEAD sea el commit revisado y que la copia esté limpia. Ejecuta primero el modo Repository desde esa copia. En Windows PowerShell 5.1 elevado, usa la raíz de la instalación estable y su directorio de estado real. Estas son las rutas de ejemplo de la guía de EC2.

~~~powershell
$audit = 'C:\Auditoria\vehiculo-iot-preflight'
$legacy = 'C:\vehiculo_iot_api_dev'
$state = Join-Path $env:ProgramData 'VehiculoIoT'
$preflight = Join-Path $audit 'deploy\staging\kw\kac_ec2_preflight_READONLY.ps1'

git -C $audit rev-parse HEAD
git -C $audit status --short
# Después de verificar el SHA y la copia limpia
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $preflight -Mode Repository
if ($LASTEXITCODE -ne 0) { throw 'NO-GO en la copia de auditoría' }
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $preflight -Mode Server -LegacyProjectRoot $legacy -LegacyStateDirectory $state
if ($LASTEXITCODE -ne 0) { throw 'NO-GO en la inspección de la instalación estable' }
~~~

El modo Server coteja las rutas de la instalación estable con el registro protegido y la configuración de las tareas. Para FastAPI exige exactamente un listener en IPv4 loopback, valida el supervisor y el proceso registrado y admite un hijo directo del lanzador virtual si coinciden la cronología, el Python base y su versión declarada en el venv, los argumentos completos de Uvicorn y los permisos de los archivos. En ese caso aparece «FastAPI: redireccionador de Python validado». Todos los listeners de Caddy deben pertenecer al PID registrado y 9444 debe estar libre. El script vuelve a comprobar los PID y listeners durante la inspección.

La salida 0 acredita la inspección observada. La salida 2 indica NO-GO. Conserva la instalación original, su configuración y sus tareas durante todo el procedimiento. La validación de GitHub Actions incluye casos sintéticos para Windows sin instalación y para una auditoría de Server desde una copia separada.

### Diagnóstico real de ACL y plan de mantenimiento (14/11/2026)

**Evidencia de EC2, obtenida solo por lectura:** el `python.exe` que escucha en `127.0.0.1:8000` es hijo directo del lanzador del `venv`, con Python base y argumentos Uvicorn compatibles. La copia de auditoría del commit `fc4c84b` pasó `Repository` pero devolvió **NO-GO / código 2** en `Server`. La revisión posterior de ACL encontró una regla `Allow FullControl` para el SID individual de la cuenta administrativa conectada: heredada en el entorno virtual, lanzador y Python base, y explícita en un padre. La cuenta coincidía con el usuario de la sesión elevada. Esto **no autoriza confiar automáticamente en ese SID**: el SID de usuario también se usa en un token sin elevación UAC. No existe evidencia de que el servidor real haya sido endurecido o de que el preflight Server apruebe.

**Correcciones offline:** el preflight ahora devuelve una categoría fija de fase y motivo de fallo de ACL, sin mostrar rutas/identidades/excepciones de Windows; rechaza DACL inexistente o nula, además de ACE de escritura heredada o explícita. Las pruebas sintéticas de PowerShell 5.1 reproducen los casos. Las modificaciones no relajan el bloqueo para cuentas individuales ni ejecutan `Set-Acl`, `icacls`, tareas o servicios.

**Procedimiento propuesto para una futura ventana de mantenimiento expresamente autorizada (NO EJECUTADO):**

1. Inventariar en privado la identidad, origen y herencia de las ACE, propietarios y permisos efectivos del árbol del `venv`, Python base y sus padres; incluir DLL, `site-packages`, código y scripts de arranque. Identificar si las rutas están en el perfil de usuario u otro árbol compartido. No asumir que una ACL resumida describe todas las rutas desde las que se cargará código.
2. Antes de modificar, preparar copia restaurable de código, configuración privada y entorno Python, exportar XML de las tareas y respaldar **DACL y propietarios** de los árboles específicos, por ejemplo usando `icacls <arbol> /save <respaldo_privado> /T` y SDDL/propietario por separado en una ubicación con acceso administrativo. Verificar la restauración en una copia aislada. `icacls /save` no guarda por sí solo el propietario. No publicar respaldos o secretos.
3. Si la regla individual nace en una carpeta compartida o perfil de usuario, **preferir una instalación protegida paralela** de Python de máquina y un checkout dedicado con identidad de servicio y rutas explícitas. No aplicar `icacls /reset` ni retirar ACE de carpetas generales de Windows. Planificar conjuntamente las rutas del `venv`, `deployment.json`, scripts y tareas; reemplazos de venv o binarios no se realizan durante inspecciones de solo lectura.
4. Con respaldo y rollback probado, validar en una ventana supervisada `Repository` y luego `Server` desde una copia de auditoría fijada al nuevo SHA; revisar HTTP/WSS legacy y restaurar la configuración si algo falla. Conservar **NO-GO** y prohibir despliegue/flags físicos mientras no aprueben seguridad, autoridad de comandos y parada física.

**Alcance:** estas son instrucciones de preparación, no una autorización para cambiar ACL de EC2 ahora. Mientras Codex/ChatGPT avanza con el código, EC2/RDS pueden permanecer detenidos y ESP/batería desconectadas.

### Componente 2: HTTPS con candidato, caída y reversión

El workflow `.github/workflows/kac-caddy-coexistence-ci.yml` ejecuta en un runner Linux efímero:

```text
curl TLS/CA comprobada, DNS local forzado a 127.0.0.1
   |
   v
Caddy 2.10.2 HTTPS:9443 — config DERIVADA en RUNNER_TEMP
   |                                          |
   +--- rutas virtuales -------------------> FastAPI K-V real 127.0.0.1:9444
   |                                          (tickets virtuales; canDrive=false)
   |
   +--- fallback --------------------------> servidor legado SINTÉTICO
                                              127.0.0.1:8000
```

Se derivan los archivos temporales `candidate.caddy` y `rollback.caddy` desde el candidato y la plantilla original, respectivamente. Se cambia únicamente el escucha HTTPS para que sea loopback 9443 con certificado efímero verificado por CA. **Los Caddyfiles del repositorio no se sobrescriben.** `curl` usa `--cacert` y `--resolve`; el dominio remoto no se consulta y no se usa `-k`/`--insecure`.

Pruebas de red que ejecuta `scripts/kac_ci_verify_roundtrip.py`:

1. **Candidato:** HTTPS legacy responde 200 desde 8000. Un intento de acceso a la admisión desde cliente loopback es rechazado 403 (el propio candidato usa `{remote_host}`, no la IP pública sintética de K-W). Se intenta inyectar falsos `X-Admission-Client-IP`, `X-Admission-Proxy-Token` y `X-Forwarded-For`, que no deben convertir la conexión loopback en un visitante autorizado. La ruta de movimientos es inexistente en el servidor legacy sintético.
2. **Caída del sidecar:** se detiene FastAPI K-V y la ruta virtual falla con HTTP 502. Mientras tanto, Caddy sigue enviando el fallback al servidor 8000, que responde 200.
3. **Reversión:** se detiene únicamente el contenedor Caddy desechable y se inicia otro con el **Caddyfile original transformado para CI**. Legacy recupera HTTPS 200 y el endpoint virtual vuelve a ser una ruta inexistente 404 del servidor sintético.

**Límites explícitos de este ensayo:** el 8000 es un sustituto HTTP sin control físico, no el backend original en EC2. El rollback se ensaya reiniciando el contenedor de laboratorio y **no garantiza una recarga de Caddy sin interrupción** ni recuperación de certificados, procesos o permisos reales en Windows. El cliente de CI es loopback: se verifica denegación de identidad, no aprobación de tickets desde una IP de Internet real. El flujo completo de tickets virtuales bajo HTTPS/Caddy ya se probó anteriormente en K-W con identidad sintética y secretos temporales.

## Archivos nuevos

- `deploy/staging/kw/kac_ec2_preflight_READONLY.ps1`: preflight de repositorio/servidor, ninguna mutación.
- `tests/kac_ec2_preflight_ci.ps1`: PowerShell 5.1 real y prueba negativa en un fixture temporal.
- `scripts/kac_ci_prepare_caddy.py`: derivación offline de candidato y rollback desde el repositorio.
- `scripts/kac_ci_legacy_stub.py`: servidor 8000 inofensivo del ensayo.
- `scripts/kac_ci_verify_roundtrip.py`: verificaciones de tres fases en HTTPS.
- `.github/workflows/kac-caddy-coexistence-ci.yml`: prueba TLS real, caída y reversión del contenedor.
- `.github/workflows/kac-windows-readonly-ci.yml`: preflight Windows de solo lectura y NO-GO por falta de instalación.
- `tests/test_kac_ec2_preparation_contract.py`: barreras de regresión.

## Bloqueos antes de probar EC2

1. **No usar** `deploy/windows/install.ps1`: detiene las dos tareas originales, actualiza binarios y las registra de nuevo. K-AC no necesita ejecutarlo.
2. Definir y probar la cuenta Windows dedicada del nuevo servicio. K-AB rechaza SYSTEM/LocalService/NetworkService fuera de CI. No se ha creado esa identidad en EC2 ni se conocen sus ACL efectivas.
3. Custodiar en Windows dos pruebas de secreto distintas, una para Caddy y otra administrativa, **fuera de Git y de la línea de comandos**. El Caddyfile candidato usa `{$KW_PROXY_TOKEN}`, pero el mecanismo seguro para que la tarea existente Caddy/SYSTEM reciba esa variable todavía no se ha configurado ni validado.
4. Mantener una **copia privada verificable del Caddyfile persistente actual** y confirmar la forma de validarlo/restaurarlo antes de recargar Caddy real. No escribir una versión del repositorio sobre el archivo persistente a ciegas.
5. Auditar que `9444` solo escucha loopback y que Security Groups y Windows Firewall no lo publican. Revisar si existe algún proxy previo antes de confiar en `{remote_host}`.
6. Probar coexistencia con el FastAPI original del puerto 8000, los endpoints CONTROL/MONITOREO, los WebSockets y su degradación cuando RDS esté apagado. Este punto no se puede concluir con la prueba del stub.
7. Integra la interfaz completa en la misma URL GitHub Pages **solo tras tener la admisión virtual accesible externamente**, manteniendo `canDrive=false`. Ningún token administrativo se incluirá en HTML/JS.
8. Para el miércoles físico: la aprobación virtual no equivale a permiso de movimientos; se necesita arbitraje único de Swagger/joystick/DEMO, STOP real, watchdog y exclusión de mandos. La batería continúa desconectada hasta esas pruebas.

**Próximo paso responsable:** revisión y recopilación de evidencia **solo lectura** del Windows EC2 durante una ventana expresamente autorizada, sin RDS, sin batería ni POST. Después preparar la cuenta dedicada, secretos, tarea sidecar y un rollback Caddy Windows probado de forma independiente. Solo cuando todo eso pase podrá pensarse en exponer las solicitudes virtuales desde el único enlace Pages.

**Estado de entrega:** https://yori7v7.github.io/control-iot-u4/ y https://github.com/yori7v7/control-iot-u4 permanecen intactos. Backend `main` intacto, PR #5 experimental en borrador.

### Evidencias CI

- K-AC convivencia HTTPS/rollback: https://github.com/yori7v7/vehiculo_iot_api_dev/actions/workflows/kac-caddy-coexistence-ci.yml
- K-AC preflight Windows: https://github.com/yori7v7/vehiculo_iot_api_dev/actions/workflows/kac-windows-readonly-ci.yml
- Regresión general backend: https://github.com/yori7v7/vehiculo_iot_api_dev/actions/workflows/backend-ci.yml
