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

El comando `-Mode Server` se reserva para una futura ventana autorizada de inspección, nunca para la preparación offline. La validación de GitHub Actions sobre un Windows sin instalación reproduce el caso **NO-GO**.

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
