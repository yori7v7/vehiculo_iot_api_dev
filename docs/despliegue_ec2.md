# Práctica 2.6: despliegue persistente en EC2 Windows Server

La API de la práctica 2.5 conserva su arquitectura por capas, las seis tablas,
los 21 Stored Procedures y los contratos de movimiento, historial, DEMO y
WebSocket. Esta guía prepara su ejecución persistente en Windows Server 2025.
No crea recursos de AWS ni modifica MySQL.

El punto de partida es `main`, commit
`405e26ce9f978aae1d1e09c9011bfd659e5cb1a8`. El usuario confirmó previamente el
funcionamiento manual de HTTPS, WSS y EC2 → RDS → SP. Las instrucciones siguientes
no constituyen evidencia de haber instalado las tareas ni de haber repetido las
pruebas funcionales en EC2.

## Arquitectura y URLs

```text
Cliente externo: Postman / navegador / futuro ESP8266 o ESP32
    |
    | HTTPS / WSS
    v
Caddy :443, hostname 100-30-4-62.nip.io
    |
    | HTTP / WebSocket por loopback
    v
FastAPI / Uvicorn 127.0.0.1:8000, un único worker
    |
    | PyMySQL con TLS, certificado y nombre de servidor verificados
    v
Amazon RDS MySQL :3306
    |
    v
vehiculo_iot: 6 tablas / 21 Stored Procedures existentes
```

| Recurso | URL pública |
| --- | --- |
| Salud del proceso | <https://100-30-4-62.nip.io/> |
| Diagnóstico de RDS | <https://100-30-4-62.nip.io/health/database> |
| Swagger UI | <https://100-30-4-62.nip.io/docs> |
| OpenAPI | <https://100-30-4-62.nip.io/openapi.json> |
| Monitoreo de un vehículo | `wss://100-30-4-62.nip.io/ws/vehiculos/{id_vehiculo}` |

`GET /` no consulta RDS ni confirma conexión física de un vehículo.
`GET /health/database` ejecuta `sp_obtener_vehiculos()` en una transacción de
sólo lectura y devuelve 200 o un error 503 sanitizado. Ninguna comprobación de
salud registra movimientos ni inicia DEMO.

## Preparar el servidor

Ejecutar esta sección en **EC2**, en una consola PowerShell elevada como
administrador. Se requieren Windows Server 2025, Git, Python 3.14.8 de 64 bits,
PowerShell 5.1 o posterior con el módulo nativo `ScheduledTasks`, acceso a RDS y
Caddy 2 instalado previamente. Python y su entorno deben poder ejecutarse desde
la cuenta `SYSTEM`, sin depender de una sesión interactiva ni de un alias de
Microsoft Store. El instalador copia el binario real de Caddy a una ubicación
estable y protegida para esa cuenta.

El directorio del proyecto y todos sus scripts, `.venv`, Python y Caddy sólo
deben poder modificarse por administradores. Las tareas ejecutan este código
como `SYSTEM`: dar escritura a un usuario sin privilegios sobre cualquiera de
estos archivos le permitiría ejecutar código con esa cuenta. `SYSTEM` debe tener
lectura de la configuración privada y de la CA. El instalador protege su
directorio de estado; no cambia los permisos del proyecto ni de Python.

Para una copia nueva:

```powershell
Set-Location C:\
git clone https://github.com/yori7v7/vehiculo_iot_api_dev.git
Set-Location C:\vehiculo_iot_api_dev
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Para un proyecto ya copiado, usar su carpeta y comprobar sus cambios antes de
actualizarlo. No volver a clonar encima ni reemplazar la configuración privada.
Los scripts de esta guía deben estar presentes en la copia del servidor antes
de instalar las tareas; publicarlos en GitHub y actualizar EC2 es un paso
posterior del operador.

### CA pública de RDS

Descargar el bundle oficial de AWS en una copia nueva:

```powershell
New-Item -ItemType Directory -Path .certs -Force | Out-Null
Invoke-WebRequest -Uri 'https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem' -OutFile .certs\rds-global-bundle.pem
```

Este archivo contiene certificados públicos, no credenciales. La conexión
mantiene la validación TLS y del hostname de RDS. Si falla, revisar la CA y el
endpoint; no desactivar la validación del certificado. Ver la
[documentación de TLS de RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html).

El instalador comprueba que exista `.certs\rds-global-bundle.pem` sin leer
`.env`. Aunque la aplicación admite configurar otra ruta absoluta mediante
`DB_SSL_CA`, para utilizar este instalador el bundle público debe estar también
en esa ubicación normal del proyecto. La ruta usada por la aplicación se elige
privadamente en la configuración del servidor.

### Configuración privada del servidor

Crear `.env` a partir de `.env.example` **sólo si aún no existe** y completar sus
valores privadamente en el servidor. Conservar cualquier archivo existente.
No copiarlo al repositorio publicado, a capturas, a colecciones de Postman o a
logs. No hace falta mostrar su contenido para instalar ni consultar las tareas.

| Variable | Configuración requerida en EC2 |
| --- | --- |
| `APP_NAME` | Nombre del servicio que se desea mostrar |
| `APP_ENV` | `production` |
| `DB_HOST` | Endpoint DNS real de RDS |
| `DB_PORT` | `3306` |
| `DB_NAME` | `vehiculo_iot` |
| `DB_USER` | Usuario autorizado de la base existente |
| `DB_PASSWORD` | Contraseña privada, configurada sólo en el servidor |
| `API_KEY` | Clave privada aleatoria para las operaciones protegidas |
| `DB_SSL_CA` | `.certs/rds-global-bundle.pem` o su ruta absoluta |
| `DB_CONNECT_TIMEOUT` | Opcional; predeterminado 5 segundos |
| `DB_READ_TIMEOUT` | Opcional; predeterminado 10 segundos |
| `DB_WRITE_TIMEOUT` | Opcional; predeterminado 10 segundos |

Las variables del proceso tienen prioridad sobre `.env`. La cuenta `SYSTEM`
no hereda las variables de la consola RDP del administrador. Configurar los
datos necesarios en el archivo del servidor y revisar que no haya variables de
máquina que los sustituyan. Tras cambiar la configuración, reiniciar las tareas
para que FastAPI la vuelva a cargar. `APP_ENV=development` sigue disponible para
desarrollo local.

### Caddy instalado previamente

Caddy ya está instalado en la instancia mediante winget. Validar su detección
en la consola elevada:

```powershell
Get-Command caddy -CommandType Application
caddy version
```

Si se prepara otro servidor, instalar Caddy antes por el procedimiento oficial
de Windows/winget y volver a abrir la consola para actualizar `PATH`; los scripts
del repositorio no lo instalan. Ver [instalación oficial](https://caddyserver.com/docs/install).
Si la detección no encuentra un ejecutable real, proporcionar su **ruta absoluta
real** mediante `-CaddyPath`. El instalador lo valida y copia a
`C:\ProgramData\VehiculoIoT\bin\caddy.exe`, evitando depender del `PATH` o del
perfil del usuario de winget al arrancar como `SYSTEM`. Tras actualizar Caddy,
volver a ejecutar el instalador: compara los hashes y actualiza esa copia cuando
corresponde.

El [Caddyfile del repositorio](../deploy/windows/Caddyfile) contiene:

```caddyfile
100-30-4-62.nip.io {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy obtiene y renueva un certificado público para ese hostname. No se usa
`tls internal`, certificados autofirmados ni excepciones de validación en los
clientes. `reverse_proxy` gestiona el upgrade WebSocket automáticamente, por lo
que el mismo bloque permite HTTPS y WSS sin cabeceras de upgrade manuales.
Referencias: [HTTPS automático](https://caddyserver.com/docs/automatic-https) y
[reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

## Instalar y operar las tareas persistentes

Desde `C:\vehiculo_iot_api_dev`, en PowerShell elevada:

```powershell
.\deploy\windows\install.ps1
.\deploy\windows\status.ps1
```

Si Caddy no está en `PATH`, usar `install.ps1 -CaddyPath` con su ruta absoluta
real. También se puede cambiar la ubicación de estado con `-StateDirectory`,
siempre a una **subcarpeta dedicada de ProgramData**; en ese caso pasar la misma
ruta a todos los scripts operativos. El instalador solicita el arranque de ambas
tareas al finalizar.

La instalación registra o actualiza exactamente dos tareas:

| Tarea | Proceso supervisado |
| --- | --- |
| `VehiculoIoT-FastAPI` | `.venv\Scripts\python.exe -m uvicorn app.main:app` |
| `VehiculoIoT-Caddy` | Caddy en primer plano con el Caddyfile de producción |

Las tareas arrancan con Windows bajo `SYSTEM`, con permisos elevados y sin
requerir inicio de sesión. Sus wrappers esperan al proceso supervisado y no
usan `caddy start` para dejarlo en segundo plano. Se configuraron hasta 999
reintentos ante fallo, separados por un minuto, exclusión de instancias
simultáneas y ausencia de límite de tiempo. El disparador de arranque espera
30 segundos después de iniciar Windows.
El Programador de tareas las mantiene independientes de VS Code, PowerShell y
RDP. No se requieren NSSM ni otros gestores de servicios.

Volver a ejecutar el instalador actualiza las mismas tareas, valida los
requisitos y conserva la configuración y los datos de estado; no crea nombres
duplicados ni reemplaza `.env`. Después de actualizar scripts o rutas, utilizar
`restart.ps1` para aplicar el cambio a los procesos que ya estaban ejecutándose.

FastAPI arranca con `--host 127.0.0.1 --port 8000 --workers 1`, sin `--reload`.
Acepta cabeceras de proxy mediante `--proxy-headers` y
`--forwarded-allow-ips 127.0.0.1`. Caddy es el único salto de red confiado para
reconstruir el esquema HTTPS/WSS. No usar `*` como lista de proxies confiables.

El único worker es necesario: las suscripciones WebSocket y la exclusión de
DEMO por vehículo viven en memoria del proceso. Multiplicar workers o iniciar
otra instancia perdería la coordinación entre clientes y ejecuciones.

Comandos administrativos:

```powershell
# Estado del Programador de tareas y procesos administrados.
.\deploy\windows\status.ps1

# Detener y deshabilitar hasta un nuevo start.
.\deploy\windows\stop.ps1

# Habilitar e iniciar nuevamente.
.\deploy\windows\start.ps1

# Detener e iniciar para aplicar configuración/código.
.\deploy\windows\restart.ps1

# Detener y eliminar las dos tareas; conservar proyecto y datos.
.\deploy\windows\uninstall.ps1
```

`stop.ps1` deshabilita las tareas para evitar que un reintento pendiente las
arranque de nuevo. Una tarea detenida de esta forma tampoco arranca en el
siguiente boot hasta ejecutar `start.ps1`. La desinstalación conserva el
proyecto, `.env`, CA, configuración, logs y almacenamiento TLS.

Antes de cambiar de los procesos manuales a las tareas, detener los procesos
manuales de FastAPI y Caddy de forma controlada. No debe haber otra instancia
ocupando 8000, 80, 443 o el puerto administrativo local de Caddy. Los scripts no
deben utilizarse para terminar procesos ajenos a sus tareas.

### Estado de Caddy, permisos y logs

El directorio predeterminado es `C:\ProgramData\VehiculoIoT`, fuera del perfil
de la sesión RDP. Contiene la configuración operativa sin secretos, los logs de
cada arranque y subdirectorios para el estado y la configuración de Caddy.
`run_caddy.ps1` establece `XDG_DATA_HOME` y `XDG_CONFIG_HOME` explícitamente;
Caddy crea sus carpetas `caddy` debajo. Allí persisten certificados, claves y
datos ACME aunque cambie el administrador conectado.

En la primera instalación se copia el Caddyfile del repositorio a
`C:\ProgramData\VehiculoIoT\Caddyfile`. Éste es el archivo operativo, validado
y conservado en instalaciones posteriores. Editar sólo el archivo del
repositorio no reemplaza el operativo. Para cambiar el hostname, modificar el
operativo en una consola elevada, validar y reiniciar:

```powershell
& 'C:\ProgramData\VehiculoIoT\bin\caddy.exe' validate --config 'C:\ProgramData\VehiculoIoT\Caddyfile' --adapter caddyfile
.\deploy\windows\restart.ps1
```

Si se eligió otro `StateDirectory`, adaptar ambas rutas y pasar ese parámetro
a `restart.ps1`. La validación debe terminar correctamente antes de reiniciar.

El instalador restringe el directorio a `SYSTEM` y `Administrators`, con
permisos heredados a sus archivos. El almacenamiento TLS contiene claves
privadas: conservarlo al reinstalar, no publicarlo en Git ni borrarlo para
resolver un problema de arranque. Al pasar de Caddy manual a `SYSTEM` se usa un
almacén separado y puede obtenerse un nuevo certificado; no repetir ese cambio
innecesariamente por los límites de emisión de la autoridad certificadora.

Consultar los archivos de `logs` para errores de arranque y usar el historial
del Programador de tareas para diagnosticar permisos o reintentos. Los wrappers
registran salida del proceso sin volcar configuración, variables de entorno,
headers de autorización ni cuerpos HTTP. Los logs son por arranque; supervisar
espacio y aplicar una retención administrativa conservando los que se necesiten
como evidencia. Un estado `Running` de la tarea no sustituye las comprobaciones
HTTP. Si se agotaron sus reintentos, corregir la causa y ejecutar `start.ps1`.

### Reinicios y DEMO

Reiniciar los procesos cierra los WebSocket: el cliente debe reconectar y
recibirá nuevamente `estado_actual` desde RDS. Los mensajes no tienen replay.
Una DEMO no se reanuda tras reinicio; se conservan en RDS los pasos ya
confirmados. Para una parada planificada, cancelar primero cualquier DEMO por
su endpoint y esperar la respuesta 200 antes de usar `stop.ps1` o
`restart.ps1`. La detención administrativa puede forzar la terminación del
proceso y no equivale a la cancelación lógica de la API.

## Red y seguridad de la instancia

Estas reglas se revisan manualmente en AWS y Windows; los scripts no cambian
Security Groups, firewall, RDP, DNS ni la base de datos.

| Acceso | Política de red |
| --- | --- |
| Internet → Caddy | TCP 443 para HTTPS/WSS |
| Internet → Caddy, si se utiliza | TCP 80 para redirección a HTTPS y challenge ACME HTTP-01 |
| Caddy → Uvicorn | Sólo loopback `127.0.0.1:8000` |
| RDP TCP 3389 | Sólo IP administrativa autorizada |
| EC2 → RDS TCP 3306 | RDS permite como origen el Security Group de EC2; nunca `0.0.0.0/0` |

Si 80 permanece cerrado, la renovación debe poder realizar el challenge
TLS-ALPN-01 por 443; verificarlo en la configuración y los logs de Caddy. El
tráfico de la aplicación utiliza HTTPS/WSS por 443. Mantener 8000 cerrado
públicamente una vez validado el despliegue y ligado siempre a loopback.
El endpoint administrativo de Caddy también debe permanecer local.

El hostname `100-30-4-62.nip.io` depende de la dirección pública
`100.30.4.62`. Si EC2 cambia de IP, actualizar el hostname/Caddyfile/URLs o
mantener una IP estable administrada en AWS. La emisión y renovación requieren
DNS correcto, reloj del servidor correcto y salida de red hacia la CA.

Se mantiene el alcance de autorización de 2.5: los GET, Swagger y el WebSocket
de monitoreo son públicos; los POST de movimiento individual, inicio y
cancelación de DEMO y los cuatro DELETE requieren `X-API-Key`. Los POST de
catálogos y PUT conservan su comportamiento previo y siguen públicos; esta
decisión limita el uso a la práctica y debe revisarse antes de otros usos.
No se incorporan roles ni autenticación del dispositivo en esta migración.

En las siete operaciones protegidas: sin header se recibe **401**; con una
clave incorrecta, vacía o duplicada, **403**. Una clave de servidor sin
configurar o con el marcador público bloquea el control con **503** cuando se
envía un header único no vacío. La clave sólo viaja en `X-API-Key` por HTTPS,
nunca en la URL, query string o JSON. En Swagger se usa **Authorize →
LocalApiKey**, sin prefijo `Bearer`. No desactivar la validación TLS en Postman.

## Comprobar disponibilidad y salida de RDP

En EC2, tras instalar e iniciar las tareas:

```powershell
.\deploy\windows\status.ps1
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/'
Invoke-RestMethod -Uri 'https://100-30-4-62.nip.io/'
Invoke-RestMethod -Uri 'https://100-30-4-62.nip.io/health/database'
(Invoke-WebRequest -Uri 'https://100-30-4-62.nip.io/docs' -UseBasicParsing).StatusCode
Get-NetTCPConnection -State Listen -LocalPort 8000 | Select-Object LocalAddress, LocalPort, OwningProcess
```

Esperar 200, `environment="production"` en `/` y
`{"status":"ok","database":"available"}` en el diagnóstico de RDS.
Confirmar que 8000 escucha únicamente en `127.0.0.1`. Si Caddy devuelve 502,
revisar primero la tarea API y su salud local; si sólo falla el diagnóstico de
RDS, revisar CA, configuración privada y conectividad EC2 → RDS.

Desde otro equipo abrir Swagger HTTPS y dos conexiones WSS de Postman.
Cerrar VS Code y todas las consolas manuales; comprobar de nuevo las URLs.
Después **cerrar la sesión RDP**, incluso finalizar la sesión en Windows,
y repetir desde el equipo externo GET `/`, GET `/health/database` y la
conexión WSS. Las tareas no pertenecen a esa sesión. Para acreditar arranque
automático, reiniciar Windows en una ventana planificada y comprobar de nuevo
desde fuera sin iniciar RDP; esperar el arranque y la obtención del certificado.
Guardar hora y respuestas como evidencia sin secretos.

## Escenarios funcionales del examen con Postman

Estas pruebas reales se ejecutan expresamente por el operador del examen.
La instalación de las tareas y la suite automatizada no las ejecutan. Usar IDs
reales obtenidos por GET, no valores supuestos. Configurar como base HTTP
`https://100-30-4-62.nip.io`; abrir las solicitudes WebSocket de Postman con
`wss://100-30-4-62.nip.io/ws/vehiculos/{id_vehiculo}`. Sustituir los marcadores
de ID por enteros existentes; las plantillas con marcadores no son JSON listo
para enviar.

Consultar antes el vehículo, sus comandos, estado, historial, DEMO y movimientos
de la DEMO mediante los GET existentes. Elegir vehículo, comando y DEMO activos
y pertenecientes al mismo vehículo. Guardar las respuestas iniciales. Las
solicitudes POST de control usan un único header `X-API-Key` con el valor privado
introducido en Postman; ocultarlo en las evidencias y quitarlo de las
exportaciones. No incluirlo en solicitudes GET o WebSocket de monitoreo.

### Prueba 1: POST HTTPS y dos clientes WSS del mismo vehículo

1. Abrir **dos solicitudes WebSocket independientes** de Postman al mismo
   vehículo. Conectar ambas y comprobar un `estado_actual` en cada una. El
   estado inicial proviene de RDS y puede ser `null` si no existe fila; abrir
   una conexión no lo modifica ni cambia `conectado`.
2. Preparar `POST /vehiculos/{id_vehiculo}/movimientos`, con autorización y
   `Content-Type: application/json`. Enviar únicamente
   `{"id_comando": <id_comando_real>}` sustituyendo el marcador por el entero.
3. Comprobar **200**, `resultado="ok"`, IDs del catálogo, comando, código,
   `fecha_actualizacion`, `conectado` y `origen="API"`.
4. Comprobar que **ambos** clientes reciben `tipo_evento="movimiento"` del
   vehículo y comando elegidos. El evento sólo se publica después del commit;
   un cliente desconectado no revierte el movimiento confirmado.
5. Consultar GET de estado e historial. El estado refleja la orden y el
   historial contiene su registro individual API. Ambos se confirmaron en la
   misma transacción con `sp_actualizar_estado` y `sp_registrar_historial`.
   El valor `conectado` se conserva y no prueba control físico.

Guardar dos mensajes iniciales, POST/respuesta, ambos eventos y lecturas
antes/después; no mostrar el header privado. No presentar un error HTTP como
movimiento confirmado.

### Prueba 2: GET público del historial reciente

Enviar `GET /vehiculos/{id_vehiculo}/historial`, sin cuerpo ni API key.
Esperar **200** con entre cero y diez registros. Con menos de diez se devuelven
los disponibles; no se inventan movimientos. El orden es
`fecha_hora DESC, id_historial DESC`. Consultarlo no elimina filas antiguas.

El endpoint conserva los orígenes existentes, incluidos `WORKBENCH`, `MANUAL`
y `API`, sin filtros por etiquetas. Los cinco registros WORKBENCH de la
práctica anterior son movimientos individuales. Los movimientos de ejecución
DEMO no se añaden porque ese flujo **nunca invoca `sp_registrar_historial`**.
Guardar el JSON, su cantidad y el orden como evidencia. La respuesta muestra
una ventana de diez filas, no un conteo completo de la tabla.

### Prueba 3: DEMO asíncrona por WSS sin historial individual

1. Guardar el historial y `GET
   /vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos` antes de ejecutar.
   Obtener **N** del número real de pasos, sus IDs, orden, comando,
   `duracion_ms` y `pausa_ms`; N no está fijado en el código.
2. Conectar el WSS del vehículo y recibir `estado_actual`.
3. Enviar `POST /vehiculos/{id_vehiculo}/demos/{id_demo}/ejecutar`, con
   `X-API-Key` y **sin cuerpo**. Esperar **202 Accepted** y
   `estado="iniciada"`. El 202 acepta la ejecución, no acredita que haya
   terminado.
4. Recibir `demo_inicio`, después **N** eventos `demo_movimiento` en el orden
   obtenido por GET y finalmente un único `demo_fin`. Comparar vehículo,
   DEMO, comandos y tiempos con la configuración, incluida la pausa final.
   Los eventos de movimiento siguen a cada commit y el estado final contiene
   el último comando aplicado. Los timestamps de control son UTC y los de
   movimiento vienen de MySQL; medir intervalos con el reloj de recepción sin
   asumir una zona horaria ausente en el dato SQL.
5. Consultar de nuevo estado e historial: el estado se actualiza y el historial
   individual debe ser idéntico al anterior. No ejecutar otros movimientos
   individuales ni editar catálogos durante esta comparación. DEMO llama
   `sp_actualizar_estado` por paso y nunca `sp_registrar_historial`.

Si aparece `demo_error` o `demo_cancelada`, registrar ese resultado y no
presentarlo como finalización exitosa. Cuando existan más de diez registros,
comprobar que no cambió el total de la tabla requiere además una lectura
completa autorizada en RDS; el GET limitado por sí solo no prueba ese total.

### Cancelación, concurrencia y aislamiento

- Con una DEMO activa, enviar `POST
  /vehiculos/{id_vehiculo}/demos/{id_demo}/cancelar` sin cuerpo y con API key.
  Esperar **200**, `estado="cancelada"` y el evento `demo_cancelada` antes de
  iniciar otra. No se revierten pasos ya confirmados, no se registra historial
  y no se inventa un comando DETENER. Una cancelación sin esa DEMO activa
  devuelve 404.
- Mientras sigue activa o preparándose una DEMO de un vehículo, otro inicio
  para **ese vehículo** debe devolver **409**, incluso si el ID de DEMO cambia.
  Se permiten ejecuciones de vehículos distintos. Elegir una secuencia con
  duración suficiente para observar el caso; no confundir una secuencia ya
  finalizada con un fallo de exclusión.
- Conectar un tercer WSS a **otro vehículo existente**. Debe recibir su propio
  `estado_actual` y no recibir los eventos de movimiento o DEMO del primero.
  Repetir una operación de prueba del primer vehículo y guardar los mensajes
  de los tres clientes para documentar el aislamiento por ID.
- Para una parada lógica adicional usar sólo el ID real de DETENER obtenido
  del catálogo, después de cancelar y esperar 200. Ese POST individual sí
  registra historial API. Cancelar DEMO por sí mismo no controla hardware.

La integración con ESP8266/ESP32 sigue siendo futura. Estos clientes podrán
consumir la API o recibir eventos cuando se diseñe esa integración, pero esta
práctica sólo persiste órdenes y difunde eventos; no afirma movimiento físico,
conectividad del dispositivo ni confirmación de sus motores.

## Suite automatizada

En una copia de desarrollo, desde la raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

La suite usa datos y conexiones simulados, sin credenciales ni escrituras en
RDS. Conserva las 326 pruebas de 2.5 y añade seis pruebas del entorno
`production`, configuración y salud: **332 pruebas aprobadas**, con 683 subtests
en la ejecución de validación de 2.6. `pip check` no detectó requisitos rotos.
La validación de scripts se realiza sin instalar tareas en el
equipo de desarrollo; la persistencia real tras boot y cierre de RDP debe
comprobarse en EC2 siguiendo esta guía.

En Windows, ejecutar además las comprobaciones del despliegue:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\tests\windows_deployment_checks.ps1
```

Estas 31 comprobaciones usan un Programador de tareas simulado y procesos
de prueba aislados; verifican reinstalación, conservación de configuración/TLS,
arranque/detención y que no queden procesos hijos al terminar el supervisor.
No requieren el archivo privado de configuración ni una CA descargada.
El auxiliar `ProcessLifetime.cs` utiliza Job Objects nativos de Windows y se
compila mediante PowerShell/.NET, sin instalar otro gestor de servicios.

Referencia de la configuración nativa del Programador de tareas:
[New-ScheduledTaskSettingsSet](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset?view=windowsserver2025-ps).
