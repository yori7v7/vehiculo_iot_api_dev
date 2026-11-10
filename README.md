# Vehículo IoT API — desarrollo y despliegue en EC2

Proyecto de las prácticas 2.5 y 2.6 de Implementación de Soluciones I. API con
Python, FastAPI, Pydantic y arquitectura por capas, que utiliza los 21 Stored
Procedures existentes de Amazon RDS MySQL. Admite desarrollo local y producción
en EC2 Windows Server 2025, con Caddy publicando HTTPS/WSS y FastAPI escuchando
únicamente en `127.0.0.1:8000`.

La [guía de despliegue EC2 y pruebas del examen](docs/despliegue_ec2.md) describe
la preparación del servidor, las dos tareas persistentes de Windows y los tres
escenarios públicos con Postman. Los scripts están en `deploy/windows/` y no
modifican AWS. En desarrollo se puede seguir usando <http://localhost:8000>.

## Integración física IoT — Unidad 3 (04/11/2026)

La versión actual también controla un vehículo RC real mediante este flujo:

`Swagger / POST HTTPS → FastAPI en EC2 → RDS MySQL → eventos WSS → ESP8266 → 74HC595 → 8 optoacopladores PC817 → control original del vehículo`.

- **Swagger público:** <https://100-30-4-62.nip.io/docs>. Funciona mientras EC2, RDS y el acceso a Internet estén disponibles.
- **Firmware:** [`firmware/Excavadora_IoT_AWS/Excavadora_IoT_AWS.ino`](firmware/Excavadora_IoT_AWS/Excavadora_IoT_AWS.ino), para NodeMCU ESP8266. DATA = D5, CLOCK = D6 y LATCH = D7; las salidas Q0–Q7 se conectan a ocho PC817 para las funciones del control original. El módulo de conectividad utiliza WiFiManager y WSS con validación de certificado.
- **Control validado físicamente:** movimientos individuales, DETENER, luces, velocidad, activación de DEMO original, comando de claxon a nivel eléctrico y DEMO principal controlada por AWS. La DEMO de AWS, su cancelación y los comandos individuales se comprobaron después de actualizar FastAPI y el firmware.
- **RN07:** los eventos de movimiento y DEMO incorporan un `id_evento` UUID hexadecimal de 32 caracteres. El firmware recuerda los 16 identificadores recientes e ignora los repetidos. Se comprobó la generación de IDs distintos en dos POST legítimos iguales y su recepción por WSS. **No se comprobó físicamente el reenvío de un JSON idéntico con el mismo ID**.
- **RN09/RN10/RN11:** intervalo de liberación de 30 ms entre diferentes salidas activas, parada automática de un movimiento individual tras 12 segundos sin nueva orden y protección frente a pérdida de Wi-Fi/errores WSS. La desconexión de Wi-Fi y la parada automática se probaron físicamente; la pérdida exclusiva de WSS sin perder Wi-Fi no se ensayó aisladamente.
- **Limitaciones conocidas:** el sistema de audio del juguete no reproduce sonidos aunque se active el comando eléctrico; DETENER libera las salidas del controlador, pero no interrumpe la DEMO interna del mando original. El montaje utiliza un 74HC595 y ocho PC817.


### Ampliación posterior: joystick de ocho direcciones (09/11/2026)

Después de la integración física original de la Unidad 3, se incorporaron dos combinaciones adicionales sin agregar pines ni optoacopladores:

| Movimiento agregado | Código lógico | Salidas 74HC595 | ID activo del vehículo 1 en RDS |
| --- | ---: | --- | ---: |
| `AVANZAR_IZQUIERDA` | `5` | Q0 + Q2 | 16 |
| `RETROCEDER_DERECHA` | `10` | Q1 + Q3 | 17 |

Se mantienen los cuatro movimientos cardinales, las otras dos diagonales, DETENER y las cuatro funciones auxiliares; el catálogo del vehículo 1 tiene 13 comandos activos. Los registros nuevos se crearon con el endpoint existente `POST /vehiculos/1/comandos` y el procedimiento `sp_crear_comando`. No se cambiaron las tablas, los 21 SP, los routers FastAPI ni Caddy.

El firmware de ocho direcciones fue compilado para NodeMCU ESP8266 (core 3.1.2), instalado por COM4 y verificado con esptool. El Monitor Serie registró WSS conectado, validación TLS del servidor, recepción de los ocho códigos de movimiento desde AWS y procesamiento de DETENER (código 0); los nuevos códigos 5 y 10 aparecen en eventos `movimiento` y en el despacho `GruaRC`. El diseño original conserva un intervalo neutro de 30 ms, parada de movimientos sostenidos tras 12 s, control de DEMO y protecciones por desconexión.

**Límite de evidencia:** estos registros demuestran recepción y procesamiento lógico en el ESP8266, no movimiento real, giro ni parada física de las dos nuevas diagonales. El control físico de la versión original se documentó por separado. El frontend está publicado en [Control IoT](https://yori7v7.github.io/control-iot-u4/) con ocho sectores de dirección; [validación posterior](https://github.com/yori7v7/control-iot-u4/blob/main/docs/validacion-funcional.md#ampliacion-posterior-joystick-de-ocho-direcciones-09112026).

El firmware publicado mantiene `AP_PASSWORD = "CONFIGURAR_LOCALMENTE"` como marcador deliberado: **no almacenar ni subir a GitHub la contraseña Wi-Fi real**. La API key y la contraseña de RDS también se mantienen solo en el entorno de despliegue.

Las pruebas automatizadas de IDs se incluyen en `tests/test_ws_event_ids.py`. Para ejecutarlas en un entorno de desarrollo con `requirements-dev.txt` instalado:

```powershell
python -m pytest tests/test_ws_event_ids.py -q
```

No hay un flujo de GitHub Actions configurado; las pruebas funcionales AWS–ESP8266 mencionadas fueron manuales. Actualizar `main` en GitHub **no reinicia ni despliega automáticamente** el servicio EC2.

## Funcionalidad conservada de la práctica 2.5

Implementado: configuración mediante variables de entorno, modelo Pydantic de
salud, router independiente, punto de entrada mínimo, Swagger UI, conexión a RDS,
gestión de transacciones, ejecución reutilizable de Stored Procedures y los
catálogos HTTP completos de Vehículos y Comandos. También están implementados
la consulta de estado, la consulta de historial y el movimiento individual
con actualización de estado y registro de historial atómicos. El WebSocket
por vehículo envía el estado inicial desde RDS y difunde movimientos confirmados.
También están implementados el CRUD de DEMO y sus movimientos, la ejecución
asíncrona, la cancelación lógica y los cinco eventos de ejecución por WebSocket.
Las operaciones de control y todas las eliminaciones se protegen con una API
key compartida mediante una dependencia reutilizable y el header `X-API-Key`.
El arranque y GET `/` no abren conexiones a RDS. GET `/health/database` sí abre
una conexión y ejecuta exclusivamente un SP de lectura.

Se utilizan funcionalmente los **21 SP existentes**, conservando su definición
SQL; ver [auditoría de integración](docs/auditoria_sp.md). En la práctica
2.5 todavía no se controlaba hardware físico; la integración real se incorporó
después en la Unidad 3. Las comprobaciones de las etapas 1 a 7 fueron de lectura.
Posteriormente se completaron las tres pruebas funcionales reales de movimiento,
historial y WebSocket con DEMO; véase la sección de pruebas funcionales.

## Requisitos e instalación en Windows

- Python 3.14.8 y Git.
- PowerShell y, opcionalmente, VS Code y Thunder Client.
- El entorno `.venv` del proyecto, que ya existe en el equipo actual.

Desde la carpeta del proyecto, activar el entorno e instalar dependencias:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip check
```

En una copia nueva del repositorio, crear el entorno antes de esos comandos:

```powershell
py -3.14 -m venv .venv
```

Si PowerShell no permite activar el entorno, se puede usar directamente su
intérprete, sin modificar políticas de ejecución:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` fija las dependencias directas: FastAPI, Uvicorn con extras
standard, Pydantic, pydantic-settings y PyMySQL con soporte RSA. PyMySQL queda
como driver de RDS MySQL: es síncrono y su API permite gestionar explícitamente
una conexión y sus transacciones. Se reutiliza la versión 1.2.3 instalada en la
etapa 1. La seguridad utiliza FastAPI y la biblioteca estándar, sin añadir
dependencias. La conexión real se verificó con Python 3.14.8.

## Configuración por entorno

Crear `.env` a partir del ejemplo sólo si aún no existe:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

| Variable | Uso | Valor inicial |
| --- | --- | --- |
| `APP_NAME` | Nombre mostrado en Swagger y salud | Vehículo IoT API |
| `APP_ENV` | `development` o `production`; usar `production` en EC2 | development |
| `DB_HOST` | Endpoint real de RDS | Vacío |
| `DB_PORT` | Puerto MySQL, entre 1 y 65535 | 3306 |
| `DB_NAME` | Base de datos existente | vehiculo_iot |
| `DB_USER` | Usuario real de RDS | Vacío |
| `DB_PASSWORD` | Contraseña real de RDS | Vacío |
| `API_KEY` | Clave privada para control y eliminación | `change-me`, marcador que debe reemplazarse sólo en `.env` |
| `DB_SSL_CA` | CA pública de RDS, ruta absoluta o relativa al proyecto | .certs/rds-global-bundle.pem |
| `DB_CONNECT_TIMEOUT` | Espera máxima de conexión, segundos (1–60) | 5 |
| `DB_READ_TIMEOUT` | Espera máxima de lectura, segundos (1–120) | 10 |
| `DB_WRITE_TIMEOUT` | Espera máxima de escritura, segundos (1–120) | 10 |

La clase `Settings` lee `.env` desde la raíz del proyecto y valida sus valores.
Las variables del proceso tienen prioridad sobre el archivo. La contraseña y
la API key usan `SecretStr`, se excluyen de la representación de configuración
y no se devuelven en las respuestas. Las credenciales RDS vacías permiten
verificar GET `/`, pero el diagnóstico de base de datos devolverá 503. Los
timeouts y la ruta de CA son opcionales; el `.env` existente no necesita cambios
si se aceptan los valores predeterminados. Reiniciar el servidor después de editar `.env`, ya
que la configuración se carga una vez por proceso.

La conexión exige TLS, valida el certificado con la CA oficial de RDS y
comprueba el nombre del servidor. Descargar la CA pública desde AWS antes de
la primera conexión en una copia nueva del proyecto:

```powershell
New-Item -ItemType Directory -Path .certs -Force | Out-Null
Invoke-WebRequest -Uri 'https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem' -OutFile .certs\rds-global-bundle.pem
```

Este bundle público ya está descargado en el equipo actual. Los archivos PEM
se excluyen de Git; no se modifica el almacén de certificados del sistema.
Si la CA falta o no es válida, el diagnóstico devuelve 503 y no se desactiva
la verificación TLS como alternativa.

Completar datos reales únicamente en `.env`. Git excluye `.env`, sus variantes,
`.venv`, cachés, claves privadas y temporales. No incluir secretos en código,
README, capturas, logs ni commits. `.env.example` debe permanecer sin secretos.

## Seguridad y autorización

Configurar `API_KEY` con una clave privada dentro de `.env` en cada servidor. El valor
`change-me` de `.env.example` es un marcador público y no autoriza solicitudes.
La clave real no se copia al código, tests, README ni archivos exportados.
Reiniciar Uvicorn después de cambiarla para recargar la configuración.

En una copia nueva, después de crear `.env`, este comando genera la clave sin
imprimirla. Conserva una clave existente y sólo reemplaza un valor vacío o un
marcador público; si hay definiciones duplicadas se detiene sin escribir:

```powershell
@'
from pathlib import Path
import re
import secrets
import shlex

path = Path(".env")
if not path.is_file():
    raise SystemExit("Primero crea .env a partir de .env.example.")
lines = path.read_text(encoding="utf-8-sig").splitlines()
indices = [i for i, line in enumerate(lines)
           if re.match(r"^\s*(?:export\s+)?API_KEY\s*=", line, re.IGNORECASE)]
if len(indices) > 1:
    raise SystemExit("API_KEY está duplicada; revisa .env sin compartir sus valores.")
if indices:
    raw = lines[indices[0]].split("=", 1)[1].strip()
    try:
        parts = shlex.split(raw, comments=True)
    except ValueError:
        raise SystemExit("Revisa el formato de API_KEY en .env sin compartir su valor.")
    value = "" if not parts else (parts[0] if len(parts) == 1 else raw)
    if value.lower() not in {"", "change-me", "changeme"}:
        raise SystemExit("Se conserva la clave local existente; no se muestra.")
    lines[indices[0]] = "API_KEY=" + secrets.token_urlsafe(32)
else:
    lines.append("API_KEY=" + secrets.token_urlsafe(32))
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("API_KEY configurada únicamente en .env; su valor no se muestra.")
'@ | .\.venv\Scripts\python.exe -
```

Esta autorización compartida se aplica a exactamente siete operaciones:

| Método | Ruta protegida | Éxito |
| --- | --- | --- |
| POST | `/vehiculos/{id_vehiculo}/movimientos` | 200 |
| POST | `/vehiculos/{id_vehiculo}/demos/{id_demo}/ejecutar` | 202 |
| POST | `/vehiculos/{id_vehiculo}/demos/{id_demo}/cancelar` | 200 |
| DELETE | `/vehiculos/{id_vehiculo}` | 204 sin cuerpo |
| DELETE | `/vehiculos/{id_vehiculo}/comandos/{id_comando}` | 204 sin cuerpo |
| DELETE | `/vehiculos/{id_vehiculo}/demos/{id_demo}` | 204 sin cuerpo |
| DELETE | `/vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos/{id_demo_movimiento}` | 204 sin cuerpo |

Los GET, Swagger y el WebSocket de monitoreo siguen siendo públicos.
Los POST de configuración de catálogos y los PUT conservan su
comportamiento actual. Consultar la API o abrir un WebSocket no autoriza a
controlar un vehículo ni cambia su estado persistido.

Con una clave válida configurada, cada operación protegida exige un único
header `X-API-Key`:

```text
X-API-Key: <clave privada>
```

- Header ausente: **401 Unauthorized**.
- Header presente pero incorrecto, vacío o duplicado: **403 Forbidden**.
- Con un header único no vacío, si `API_KEY` está configurada vacía o con los
  marcadores `change-me`/`changeme`: **503 Service Unavailable**; el control
  queda bloqueado hasta corregirla.

Estos fallos devuelven un mensaje público sanitizado, sin mostrar la clave
esperada ni el valor recibido. Una solicitud rechazada no ejecuta el flujo de
control o eliminación.

En Swagger UI, local en <http://localhost:8000/docs> o público en
<https://100-30-4-62.nip.io/docs>, pulsar **Authorize** y completar
el esquema **LocalApiKey** con la clave privada, sin prefijo `Bearer`. Se conserva
el nombre del esquema para mantener compatibilidad. Swagger
envía `X-API-Key` en las operaciones protegidas y muestra sus candados. En
Thunder Client, agregar el mismo header únicamente a las solicitudes que lo
requieren. No colocar la clave en la URL, query string ni cuerpo JSON; ocultarla
en capturas y quitarla antes de exportar una colección. Las operaciones reales
de escritura forman parte de las pruebas funcionales cuando el operador las
ejecuta expresamente; instalar las tareas no ejecuta movimientos ni DEMO.

## Ejecutar FastAPI localmente

Desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

El servidor escucha en la interfaz local. Detenerlo con `Ctrl+C`.
Este comando con `--reload` es exclusivamente para desarrollo. Para producción,
usar las tareas de la [guía EC2](docs/despliegue_ec2.md), con un único worker,
sin recarga y con cabeceras de proxy aceptadas sólo desde `127.0.0.1`.

- Salud: <http://localhost:8000/>
- Diagnóstico RDS: <http://localhost:8000/health/database>
- Swagger UI: <http://localhost:8000/docs>
- Esquema OpenAPI: <http://localhost:8000/openapi.json>

## Endpoints disponibles

| Método | Ruta | Propósito | Respuesta | Stored Procedure |
| --- | --- | --- | --- | --- |
| GET | `/` | Comprobar que FastAPI responde | 200, `HealthResponse` | Ninguno |
| GET | `/health/database` | Verificar Python → RDS → SP de lectura | 200, `DatabaseHealthResponse`; 503 ante fallo | `sp_obtener_vehiculos()` |
| POST | `/vehiculos` | Crear vehículo | 201, `VehicleResponse` | `sp_crear_vehiculo` y `sp_obtener_vehiculo` |
| GET | `/vehiculos` | Listar activos e inactivos | 200, lista de `VehicleResponse` | `sp_obtener_vehiculos` |
| GET | `/vehiculos/{id_vehiculo}` | Obtener por ID | 200, `VehicleResponse`; 404 | `sp_obtener_vehiculo` |
| PUT | `/vehiculos/{id_vehiculo}` | Reemplazar campos editables | 200, `VehicleResponse`; 404 | `sp_obtener_vehiculo`, `sp_actualizar_vehiculo` y relectura |
| DELETE | `/vehiculos/{id_vehiculo}` | Eliminar físicamente | 204 sin cuerpo; 404/409 | `sp_obtener_vehiculo` y `sp_eliminar_vehiculo` |
| POST | `/vehiculos/{id_vehiculo}/comandos` | Crear comando del vehículo | 201, `CommandResponse`; 404/409 | `sp_obtener_vehiculo`, `sp_crear_comando` y `sp_obtener_comandos_vehiculo` |
| GET | `/vehiculos/{id_vehiculo}/comandos` | Listar comandos del padre | 200, lista de `CommandResponse`; 404 | `sp_obtener_vehiculo` y `sp_obtener_comandos_vehiculo` |
| PUT | `/vehiculos/{id_vehiculo}/comandos/{id_comando}` | Reemplazar un comando propio | 200, `CommandResponse`; 404/409 | Lecturas de padre/comandos, `sp_actualizar_comando` y relectura |
| DELETE | `/vehiculos/{id_vehiculo}/comandos/{id_comando}` | Eliminar un comando propio | 204 sin cuerpo; 404/409 | Lecturas de padre/comandos y `sp_eliminar_comando` |
| GET | `/vehiculos/{id_vehiculo}/estado` | Consultar estado almacenado | 200, `StateResponse` o null; 404 | `sp_obtener_vehiculo` y `sp_obtener_estado` |
| GET | `/vehiculos/{id_vehiculo}/historial` | Consultar hasta diez registros recientes | 200, lista de `HistoryResponse`; 404 | `sp_obtener_vehiculo` y `sp_obtener_historial` |
| POST | `/vehiculos/{id_vehiculo}/movimientos` | Registrar un movimiento de un comando existente | 200, `MovementResponse`; 404/409 | Lecturas de vehículo/comandos/estado, `sp_actualizar_estado`, `sp_registrar_historial` y relectura de estado |

Las tablas resumen éxito y errores de negocio. Swagger declara los errores
relevantes de cada operación, incluidos 422, 500 y 503 cuando corresponden.
Las siete operaciones de la sección de seguridad añaden 401/403 y el fallo
503 de configuración de autorización; las consultas no requieren API key.
La [auditoría HTTP](docs/auditoria_http.md) detalla los códigos por operación.

GET `/` no requiere parámetros ni cuerpo. Con la configuración inicial responde:

```json
{
  "status": "ok",
  "service": "Vehículo IoT API",
  "environment": "development"
}
```

Esta respuesta sólo verifica el proceso HTTP. No indica que RDS ni un vehículo
estén conectados.

GET `/health/database` tampoco requiere parámetros ni cuerpo. Abre una
transacción `READ ONLY`, llama `sp_obtener_vehiculos()` sin parámetros, consume
todos sus resultados y finaliza con `rollback` y cierre de la conexión. Una
lista de vehículos vacía también indica una ejecución correcta. Devuelve
únicamente:

```json
{"status": "ok", "database": "available"}
```

Ante configuración incompleta, fallo de conexión, error del SP o fallo al
terminar la transacción devuelve HTTP 503:

```json
{"detail": "No fue posible completar la comprobación de lectura de la base de datos."}
```

El diagnóstico no devuelve registros de vehículos, host, usuario, contraseña ni
mensajes originales del driver. La función de ruta es síncrona (`def`), por lo
que FastAPI ejecuta toda la operación en su pool de hilos, fuera del event loop.

## Modelos y validación de catálogos

`VehicleCreate`, `VehicleUpdate` y `VehicleResponse` separan creación,
actualización y respuesta. Lo mismo hacen `CommandCreate`, `CommandUpdate` y
`CommandResponse`. Los identificadores se envían en la ruta; los modelos de
entrada rechazan campos adicionales, incluidos IDs y fechas asignados por MySQL.

| Dato | Validación de entrada |
| --- | --- |
| IDs de vehículo y comando | Entero positivo, máximo 2147483647 |
| Nombre de vehículo | Obligatorio, no vacío ni sólo espacios, máximo 80 caracteres |
| Modelo de vehículo | NULL u opcional, máximo 80 caracteres |
| Descripción | NULL u opcional, máximo 255 caracteres |
| Microcontrolador | NULL u opcional, máximo 50 caracteres |
| Nombre de comando | Obligatorio, no vacío ni sólo espacios, máximo 60 caracteres |
| Código de comando | Entero JSON estricto, de -2147483648 a 2147483647; admite cero y negativos |
| Activo en PUT | Booleano JSON estricto y obligatorio: `true` o `false` |

Los POST no reciben `activo`; los SP utilizan el valor predeterminado TRUE de
MySQL. Los PUT realizan reemplazo completo de los campos editables: exigen
nombre y activo, y además código en comandos. Los campos opcionales omitidos
quedan en NULL. El propietario de un comando no se cambia mediante PUT.
No se interpretan los códigos como movimientos ni se impone un catálogo nuevo.

Las respuestas incluyen las columnas reales. `fecha_registro` de vehículo se
representa como fecha/hora o NULL según el resultado de MySQL. El TINYINT 0/1 de
`activo` se convierte en booleano. Los SP de lectura incluyen inactivos; estos
catálogos permiten consultarlos, modificarlos y reactivarlos.

## Existencia, pertenencia y escrituras

`VehicleService` y `CommandService` coordinan una transacción por operación.
Las lecturas usan `READ ONLY`. Las escrituras consultan los recursos necesarios,
ejecutan el SP y validan la representación resultante antes de un único commit.
Si una validación o un SP falla, se solicita rollback y no se comunica éxito.
Un PUT idéntico al registro actual sigue siendo una operación válida con 200.

Antes de actualizar/eliminar vehículos se consulta `sp_obtener_vehiculo`.
Comandos verifica ese padre antes de cualquier operación. Como no existe un SP
individual de comandos, el servicio localiza el ID entre los resultados de
`sp_obtener_comandos_vehiculo` para comprobar pertenencia antes de modificarlo.
Un recurso ausente o un comando de otro vehículo produce 404; un listado
válido vacío devuelve 200 con `[]`.

MySQL resuelve las restricciones UNIQUE de comandos `(id_vehiculo, codigo)` y
`(id_vehiculo, nombre)`. No se intenta reproducir su collation en Python: con
`utf8mb4_0900_ai_ci` nombres que difieren sólo en mayúsculas o acentos pueden
entrar en conflicto. Se responde 409 sin mostrar valores ni mensajes de MySQL.

DELETE aplica la eliminación física del SP. En vehículos conserva el
comportamiento de cascadas del esquema; en comandos, referencias existentes
pueden impedir eliminar y producir 409. Esta etapa implementa y prueba
las escrituras con datos simulados: **no se ejecutan POST, PUT ni DELETE contra
los datos académicos existentes durante la verificación real**.

## Estado e historial

`StateService` y `HistoryService` comprueban el vehículo mediante
`VehicleRepository` y ejecutan su lectura en la misma transacción `READ ONLY`.
Los vehículos inactivos también se pueden consultar. No insertan ni actualizan
filas y no hacen commit.

- Vehículo inexistente: 404 en ambos GET.
- Vehículo existente sin estado: 200 con JSON `null`; no se fabrica una fila.
- Estado existente: 200 con las columnas reales de `sp_obtener_estado`.
- Vehículo existente sin historial: 200 con `[]`.

`StateResponse` contiene `id_vehiculo`, `vehiculo`, `id_comando`, `comando`,
`codigo`, `conectado` y `fecha_actualizacion`. El SP no devuelve `id_estado`.
El comando puede ser NULL por el LEFT JOIN, y la fecha admite NULL según SQL.

`HistoryResponse` contiene `id_historial`, `id_vehiculo`, `comando`, `codigo`,
`fecha_hora` y `origen`. El SP no devuelve `id_comando`. Se admite un
`id_historial` BIGINT positivo hasta 9223372036854775807, no sólo el rango INT
de IDs de vehículo/comando. Nombre, código y fecha pueden ser NULL.

El repositorio conserva todas las filas del SP. `HistoryService` aplica
únicamente `history[:10]`: mantiene `fecha_hora DESC, id_historial DESC` tal como
lo entrega MySQL, no reordena, no borra y **no filtra por origen**. Incluye
`WORKBENCH`, `MANUAL`, `API` y cualquier otro valor ya almacenado. Los cinco
registros WORKBENCH existentes corresponden a pruebas manuales de la práctica
anterior, según confirmó el usuario. No se ocultan registros mediante etiquetas.

## Movimiento individual y atomicidad

Ruta: **POST `/vehiculos/{id_vehiculo}/movimientos`**. Usa un comando existente
del catálogo; no crea un comando. Cuerpo mínimo, mostrado sólo para preparar la
futura prueba, sin ejecutarlo contra RDS durante esta etapa:

```text
{"id_comando": <id_comando_real_del_catalogo>}
```

La plantilla se completa con un entero obtenido de GET
`/vehiculos/{id_vehiculo}/comandos`; el marcador no es JSON ejecutable.
La solicitud requiere `X-API-Key`. No se supone que un comando tenga el mismo
ID en distintos vehículos.

`MovementRequest` sólo admite `id_comando`, entero JSON estricto positivo hasta
2147483647. Rechaza valores booleanos, conversiones de texto/flotantes y campos
adicionales como `origen`, `conectado`, `codigo` o datos de un comando nuevo.

`MovementService` abre una única conexión/transacción y crea un solo ejecutor
que comparte con los repositorios:

1. Consulta `sp_obtener_vehiculo` y comprueba existencia y activo.
2. Consulta `sp_obtener_comandos_vehiculo` y comprueba ID, pertenencia y activo
   del comando solicitado. No sustituye esas lecturas con SELECT directo.
3. Consulta `sp_obtener_estado` para conservar exactamente `conectado`. Si no
   hay fila usa `false`, coherente con el default conservador del esquema.
4. Ejecuta `sp_actualizar_estado(id_vehiculo, id_comando, conectado)`.
5. Ejecuta `sp_registrar_historial(id_vehiculo, id_comando, "API")`.
6. Relee `sp_obtener_estado`, valida que los datos correspondan al movimiento y
   construye la respuesta con su timestamp real dentro de la transacción.
7. Sale del contexto, realiza **un solo commit** y cierra la conexión.
8. El router recibe el resultado confirmado, publica un evento `movimiento`
   sólo a los suscriptores de ese vehículo y devuelve 200.

Si falla una validación, SP, result set, relectura o commit, la excepción se
propaga y el contexto intenta rollback de toda la transacción y cierra la
conexión. Si falla actualizar estado, no se llama al registro de historial; si
falla registrar historial después de actualizar estado, ambos cambios se
revierten. No hay commits en repositorios ni en el ejecutor. Se comprobó mediante
metadatos de lectura que las tablas reales `estado_vehiculo` e
`historial_comandos` usan **InnoDB**, que soporta estas transacciones.

Un vehículo/comando inexistente o ajeno produce 404; uno inactivo produce 409.
No se rechaza el movimiento por `conectado=false`: recibir HTTP no acredita
conectividad física. Si el estado ya decía true se conserva true; si decía
false se conserva false. No existe parámetro HTTP para manipularlo.

`MovementResponse` incluye `resultado="ok"`, `id_vehiculo`, `id_comando`,
`comando`, `codigo`, `fecha_actualizacion`, `conectado` y `origen="API"`.
La fecha se obtiene del SP, sin fabricar un timestamp del POST ni asignarle una
zona horaria no indicada por MySQL. No se inventan IDs de movimiento/historial.
El origen API es fijo y no lo decide el cliente. El evento WebSocket representa
la orden persistida; no confirma que el hardware la haya ejecutado físicamente.

## Arquitectura

Se conservan las carpetas iniciales y se añaden las capas `app/errors/`,
`app/execution/` y `app/security/` para errores, ejecución y autorización.

```text
app/
├── config/
│   └── settings.py       # Clase Settings y carga del entorno
├── database/
│   ├── connection.py     # MySQLDatabase: apertura, transacciones y cierre
│   └── procedures.py     # StoredProcedureExecutor y ProcedureResult
├── errors/
│   ├── database.py       # Excepciones controlables sin datos sensibles
│   ├── domain.py         # Recursos inexistentes
│   └── handlers.py       # Traducción de errores de dominio y persistencia
├── models/
│   ├── common.py         # IDs, solicitudes sin extras y error público
│   ├── health.py         # Salud HTTP y RDS
│   ├── vehicles.py       # VehicleCreate/Update/Response
│   ├── commands.py       # CommandCreate/Update/Response
│   ├── state.py          # StateResponse con columnas reales del SP
│   ├── history.py        # HistoryResponse con BIGINT de historial
│   ├── movement.py       # MovementRequest y MovementResponse
│   ├── demos.py          # DEMO y movimientos configurados
│   └── demo_execution.py # Snapshot congelado y respuesta de control
├── repositories/
│   ├── base.py           # Validación de filas e IDs devueltos por SP
│   ├── vehicles.py       # Los cinco SP de Vehículos
│   ├── commands.py       # Los cuatro SP de Comandos
│   ├── state.py          # Obtener/actualizar estado
│   ├── history.py        # Consultar/registrar historial
│   └── demos.py          # DemoRepository y DemoMovementRepository
├── routers/
│   ├── health.py         # Salud HTTP y diagnóstico RDS
│   ├── vehicles.py       # CRUD de vehículos
│   ├── commands.py       # Comandos por vehículo
│   ├── state.py          # GET estado
│   ├── history.py        # GET historial
│   ├── movement.py       # POST movimiento individual
│   ├── demos.py          # CRUD de DEMO y sus movimientos
│   └── demo_execution.py # Inicio y cancelación
├── services/
│   ├── database_health.py # Lectura segura con sp_obtener_vehiculos
│   ├── vehicles.py       # Existencia y transacciones de vehículos
│   ├── commands.py       # Padre, pertenencia y transacciones de comandos
│   ├── state.py          # Padre y estado sin escrituras
│   ├── history.py        # Padre y máximo diez, sin filtro de origen
│   ├── movement.py       # Reglas y transacción atómica de movimiento
│   ├── demos.py          # CRUD de DEMO y sus movimientos
│   └── demo_execution.py # Preparación y transacción por paso
├── execution/
│   ├── manager.py        # DemoExecutionManager: tareas, tiempos y cancelación
│   └── dependencies.py   # Manager por aplicación
├── security/
│   └── api_key.py        # Dependencia require_api_key y esquema LocalApiKey
├── websocket/
│   ├── events.py         # Modelos de estado_actual y movimiento
│   ├── manager.py        # WebSocketManager: clientes y difusión por vehículo
│   ├── dependencies.py   # Manager compartido por aplicación
│   ├── router.py         # Suscripción y estado inicial de sólo lectura
│   ├── publisher.py      # Publicación del movimiento ya confirmado
│   └── demo_events.py    # Los cinco eventos de ejecución DEMO
├── dependencies.py       # Composición de la fábrica de conexiones por solicitud
└── main.py               # Construcción de FastAPI y registro de routers
```

Flujo actual: cliente HTTP → router → servicio → repositorio → ejecutor de
Stored Procedures → conexión a RDS. Tras retornar el servicio de movimiento,
el router llama a `MovementEventPublisher`, que difunde el resultado mediante
`WebSocketManager`. El servicio de persistencia no administra sockets.
`main.py` sigue siendo el punto de composición y cierra los clientes al terminar.

## Conexiones y transacciones reutilizables

`MySQLDatabase` recibe `Settings`, valida que existan los datos de conexión y
abre una conexión nueva por contexto, con `DictCursor`, `utf8mb4`, timeouts y
`autocommit=False`. Utiliza `SSLContext` con CA, certificado y hostname
verificados, y TLS 1.2 o superior. La instancia conserva configuración, no una conexión
compartida entre solicitudes o hilos. No hay reconexiones ni reintentos
automáticos en mitad de una transacción.

- `with database.transaction() as connection`: comienza la transacción, permite
  ejecutar varios SP sobre esa conexión y realiza un solo `commit` al salir
  correctamente. Ante una excepción intenta `rollback` y propaga el fallo.
- `with database.transaction(read_only=True) as connection`: comienza con
  `START TRANSACTION READ ONLY`; finaliza con `rollback`, incluso si la lectura
  fue exitosa. Nunca hace `commit`.
- Siempre se intenta cerrar la conexión. Un error durante la limpieza no oculta
  la excepción original. Si falla un `commit` no se comunica éxito ni se
  reintenta, porque su resultado puede ser incierto si se perdió la conexión.

El propietario del contexto controla la transacción completa. El código dentro
del bloque no debe cerrar ni confirmar la conexión, ni ocultar excepciones que
requieran rollback.

## Ejecutor de Stored Procedures

`StoredProcedureExecutor` recibe la conexión existente. Su método
`execute(nombre, parametros=())` pasa los valores a `cursor.callproc`; no
construye SQL concatenando datos externos. El nombre debe ser una constante
interna de servicio/repositorio y además se valida con el formato
`sp_[A-Za-z0-9_]+`. El nombre del SP no se acepta desde una petición HTTP.

El ejecutor obtiene todas las filas y recorre `nextset()` hasta el final,
incluyendo el resultado vacío que añade MySQL a `CALL`. Conserva los conjuntos
tabulares vacíos y propaga fallos en resultados posteriores antes de permitir
un commit. No confirma, revierte ni cierra la conexión; sólo administra su
cursor. Sirve para SP de lectura o escritura, con cero o varios parámetros IN.
Los procedimientos proporcionados usan parámetros IN; no se añade soporte
especulativo para OUT/INOUT.

Devuelve `ProcedureResult`:

- `fetch_one()`: primera fila del primer conjunto o `None`.
- `fetch_all()`: filas del primer conjunto o `[]`.
- `result_sets`: todos los conjuntos tabulares, en el orden recibido.

Ejemplo de lectura usando el procedimiento real, sin imprimir sus registros:

```python
from app.config.settings import get_settings
from app.database.connection import MySQLDatabase
from app.database.procedures import StoredProcedureExecutor

database = MySQLDatabase(get_settings())
with database.transaction(read_only=True) as connection:
    result = StoredProcedureExecutor(connection).execute("sp_obtener_vehiculos")
    first_vehicle = result.fetch_one()
    vehicles = result.fetch_all()
```

Los servicios de catálogos y movimiento individual coordinan sus transacciones.
El publicador WebSocket recibe únicamente el resultado que el servicio devuelve
después de confirmar la transacción; no participa en ella.

## Fuente de verdad

El archivo proporcionado `vehiculo_iot_rds.sql`, actualmente externo al
repositorio, define las seis tablas y los 21 Stored Procedures existentes de
`vehiculo_iot`. Debe consultarse antes de implementar acceso a datos; no ejecutar
el script para arrancar esta API ni alterar la estructura de RDS.

Los tags Salud, Vehículos, Comandos, Estado, Historial, Movimientos y DEMO están
disponibles en Swagger. WebSocket se documenta a continuación porque OpenAPI
no representa una suscripción como un endpoint HTTP convencional.

## WebSocket por vehículo

URL exacta: **`ws://localhost:8000/ws/vehiculos/{id_vehiculo}`**.
Ejemplo de lectura: `ws://localhost:8000/ws/vehiculos/1`.
`id_vehiculo` debe ser un entero positivo de hasta 2147483647.
Esta suscripción pública de monitoreo no requiere API key; nunca añadir la
clave a la URL del WebSocket.

Al conectar, la ruta reutiliza `StateService.get`: comprueba el vehículo con
`sp_obtener_vehiculo` y consulta `sp_obtener_estado` en la misma transacción
`READ ONLY`. PyMySQL se ejecuta en un hilo mediante `run_in_threadpool`, fuera
del event loop. No se actualizan estado, historial ni el campo `conectado`.
Un suscriptor de monitoreo no acredita conectividad del hardware.

La primera entrega es `estado_actual`. Ejemplo ilustrativo de una fila existente
(los valores siempre se consultan en RDS):

```json
{
  "tipo_evento": "estado_actual",
  "id_vehiculo": 1,
  "comando": "DETENER",
  "codigo": 0,
  "timestamp": "2026-10-06T23:54:43",
  "estado": {
    "id_vehiculo": 1,
    "vehiculo": "Mini RC Forklift IoT",
    "id_comando": 1,
    "comando": "DETENER",
    "codigo": 0,
    "conectado": true,
    "fecha_actualizacion": "2026-10-06T23:54:43"
  }
}
```

Si el vehículo existe pero aún no tiene estado, se entrega sin crear ninguna fila:

```json
{"tipo_evento":"estado_actual","id_vehiculo":1,"comando":null,"codigo":null,"timestamp":null,"estado":null}
```

El evento `movimiento` reutiliza los valores de la respuesta HTTP confirmada:

```json
{
  "tipo_evento": "movimiento",
  "id_vehiculo": 1,
  "comando": "DETENER",
  "codigo": 0,
  "timestamp": "2026-10-14T12:30:45",
  "id_comando": 1,
  "conectado": true,
  "origen": "API"
}
```

Todos los eventos incluyen `tipo_evento`, `id_vehiculo`, `comando`, `codigo` y
`timestamp`. La fecha proviene de `fecha_actualizacion` de MySQL, admite `null`
y no incorpora una zona horaria inventada. El estado puede contener comando
y código `null` según el LEFT JOIN del SP.

`WebSocketManager` mantiene grupos en memoria por ID de vehículo y varios
sockets por grupo. Cada cliente recibe primero su estado y después los eventos
del vehículo que monitorea. Un lock por vehículo coordina lectura inicial,
registro y difusión para que una publicación concurrente no se pierda entre
la lectura y la suscripción. Los envíos a distintos clientes de un grupo se
realizan concurrentemente. Vehículos distintos tienen grupos y locks separados.

El POST conserva su transacción original: **commit exitoso → cierre de conexión
RDS → publicación WebSocket → respuesta HTTP**. Cada POST exitoso solicita una
sola difusión. Ante rollback o fallo de commit no publica ningún movimiento.
Si no hay suscriptores, responde normalmente; un fallo de notificación tampoco
revierte una escritura confirmada ni la reintenta.

La desconexión normal o inesperada elimina al cliente sin afectar a los demás.
Un fallo o timeout de envío elimina y cierra sólo ese socket. Los envíos y
cierres tienen una espera acotada de cinco segundos. La limpieza completa el
cierre acotado aunque se cancele la tarea que lo solicitó. Los grupos vacíos se
eliminan cuando no quedan operaciones pendientes. Reconectar crea una nueva
suscripción y vuelve a leer el estado actual. La ruta sólo recibe mensajes para
detectar el cierre; no ejecuta órdenes enviadas por el cliente WebSocket.

ID inválido o vehículo ausente: cierre controlado 1008. Error al consultar RDS:
cierre 1011, con razón pública fija. Se rechaza antes de aceptar la conexión,
por lo que un cliente de red puede observar HTTP 403 durante el handshake en
lugar del código de cierre. No se registra el socket rechazado ni se muestran
errores internos. Al detener o recargar la aplicación se cierran los clientes
activos con 1001.

El manager pertenece a una aplicación/proceso. Usar una sola instancia de
Uvicorn y un único worker tanto en desarrollo como en producción. Reinicios requieren reconectar; los eventos
transitorios no tienen replay ni entrega persistente. RDS conserva la fuente
de verdad y cada reconexión vuelve a consultarla.

Para comprobar sólo el estado inicial con la dependencia `websockets` que ya
incluye Uvicorn standard, ejecutar este Python desde el entorno del proyecto:

```python
import asyncio
from websockets.asyncio.client import connect

async def comprobar_estado():
    async with connect("ws://localhost:8000/ws/vehiculos/1", open_timeout=30) as ws:
        print(await asyncio.wait_for(ws.recv(), timeout=30))

asyncio.run(comprobar_estado())
```

Esta comprobación sólo lee. No ejecutar el POST real durante esta etapa.

## DEMO: configuración y ejecución

Todos los endpoints siguientes aparecen bajo el tag **DEMO** de Swagger.
`id_vehiculo`, `id_demo` e `id_demo_movimiento` son IDs positivos INT.
Iniciar, cancelar y ambos DELETE requieren `X-API-Key`; los GET, POST de
configuración y PUT conservan el acceso descrito en la sección de seguridad.

| Método | Ruta exacta | Éxito | SP principal |
| --- | --- | --- | --- |
| POST | `/vehiculos/{id_vehiculo}/demos` | 201, `DemoResponse` | `sp_crear_demo` |
| GET | `/vehiculos/{id_vehiculo}/demos` | 200, lista | `sp_obtener_demos` |
| PUT | `/vehiculos/{id_vehiculo}/demos/{id_demo}` | 200, `DemoResponse` | `sp_actualizar_demo` |
| DELETE | `/vehiculos/{id_vehiculo}/demos/{id_demo}` | 204 | `sp_eliminar_demo` |
| POST | `/vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos` | 201, `DemoMovementResponse` | `sp_agregar_movimiento_demo` |
| GET | `/vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos` | 200, lista | `sp_obtener_movimientos_demo` |
| PUT | `/vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos/{id_demo_movimiento}` | 200, `DemoMovementResponse` | `sp_actualizar_movimiento_demo` |
| DELETE | `/vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos/{id_demo_movimiento}` | 204 | `sp_eliminar_movimiento_demo` |
| POST | `/vehiculos/{id_vehiculo}/demos/{id_demo}/ejecutar` | 202, `DemoExecutionResponse` | Lecturas de validación y `sp_actualizar_estado` por paso |
| POST | `/vehiculos/{id_vehiculo}/demos/{id_demo}/cancelar` | 200, `DemoExecutionResponse` | Control de tarea; ningún SP propio |

El CRUD comprueba vehículo y pertenencia de la DEMO; los movimientos comprueban
además su pertenencia a la DEMO. Un recurso ausente o ajeno devuelve 404; una
colección válida vacía devuelve 200 `[]`. Las escrituras releen y validan el
resultado antes del commit. Crear un movimiento identifica su ID mediante
diferencia de IDs y orden único: el SP de alta no devuelve `LAST_INSERT_ID`.
No se añade SQL directo. La auditoría enlazada arriba detalla todos los SP de
validación y relectura, además de los principales de esta tabla.

Crear DEMO recibe `{"nombre":"Recorrido","descripcion":null}`; nombre no
vacío hasta 80 caracteres, descripción opcional hasta 255. PUT añade `activo`,
booleano JSON estricto obligatorio. Los campos adicionales se rechazan. El
CRUD permite administrar catálogos inactivos; ejecutar exige vehículo y DEMO
activos. La creación usa el default activo de MySQL.

Crear un movimiento recibe, por ejemplo:

```json
{"id_comando":1,"orden":1,"duracion_ms":1200,"pausa_ms":300}
```

El comando debe estar activo y pertenecer al vehículo. `orden` es positivo;
`duracion_ms` y `pausa_ms` son enteros JSON estrictos no negativos. Todos llegan
a SP con parámetros INT firmados, por lo que su máximo de entrada es 2147483647.
En POST, `pausa_ms` omitida usa cero; PUT exige todos los campos, incluida la
pausa. Las lecturas admiten hasta 4294967295 ms almacenados porque las columnas
son INT UNSIGNED, aunque las firmas de escritura sean INT. Se conserva también
el orden INT firmado de filas existentes; la ejecución rechaza órdenes no
positivos, repetidos o fuera de secuencia. No se impone que sean consecutivos.
MySQL resuelve UNIQUE `(id_demo, orden)`; un conflicto devuelve 409 sin detalles
internos. Entradas inválidas producen 422 y errores de infraestructura 500/503.

### Inicio, orden y tiempos

El POST de ejecución requiere `X-API-Key` y no recibe cuerpo.
`DemoExecutionService.prepare` consulta
el vehículo, DEMO, comandos y **N pasos de `sp_obtener_movimientos_demo`** en una
transacción READ ONLY. Valida activo, propiedad, secuencia no vacía y coherencia
del comando. No hay IDs, códigos, seis pasos ni tiempos de la DEMO real en el
código. El resultado es un snapshot congelado; el CRUD posterior no modifica
los pasos que ya se validaron para esa ejecución.

`DemoExecutionManager` reserva el vehículo antes de validar para impedir carreras
de inicio. Tras la validación crea una tarea y responde, sin esperar los N pasos:

```json
{"id_vehiculo":1,"id_demo":1,"estado":"iniciada"}
```

La respuesta es **202 Accepted**. Cada paso, en el orden exacto del SP, realiza:

1. Revalidar vehículo, DEMO y comando, incluidos activo y datos del comando.
2. Leer el estado actual para conservar `conectado`, o usar false si no existe.
3. Ejecutar `sp_actualizar_estado`, releer y validar el resultado.
4. Hacer commit y cerrar la conexión; sólo entonces emitir `demo_movimiento`.
5. Esperar `duracion_ms / 1000` segundos y luego `pausa_ms / 1000` segundos.

La pausa se aplica después de **cada** paso, incluido el último: `demo_fin`
se emite después de su duración y pausa. Cero es válido y permite continuar
cooperativamente. Las esperas usan asyncio y pueden sustituirse en pruebas.
PyMySQL se ejecuta en hilos, sin bloquear el event loop. Cada paso tiene una
transacción nueva; cancelar o fallar un paso no revierte pasos ya confirmados.
No se fuerza `conectado=true`, ni se usa el valor inicial durante toda la DEMO:
se vuelve a leer en cada actualización.

**DEMO nunca llama `sp_registrar_historial`.** No reutiliza el servicio del
movimiento individual. El historial no se filtra por origen para ocultar DEMO;
su exclusión se garantiza evitando el registro. La ejecución todavía no
controla físicamente el ESP8266 ni acredita una orden ejecutada por hardware.

### Eventos, concurrencia y cancelación

Se reutiliza **`ws://localhost:8000/ws/vehiculos/{id_vehiculo}`**. Cada cliente
recibe su `estado_actual` al conectar y después, para la ejecución de su vehículo:

```text
demo_inicio → demo_movimiento (N veces) → demo_fin
                                     ↘ demo_cancelada o demo_error
```

Todos los eventos DEMO contienen `tipo_evento`, `id_vehiculo`, `id_demo`,
`nombre_demo`, `comando`, `codigo` y `timestamp`. Los campos que no corresponden
a ese evento son null. Ejemplo ilustrativo de un movimiento confirmado:

```json
{
  "tipo_evento":"demo_movimiento",
  "id_vehiculo":1,"id_demo":1,"nombre_demo":"Recorrido",
  "id_demo_movimiento":9,"id_comando":1,"comando":"DETENER","codigo":0,
  "orden":2,"duracion_ms":1200,"pausa_ms":300,
  "conectado":true,"timestamp":"2026-10-14T12:30:45","mensaje":null
}
```

`demo_movimiento` usa el timestamp y los valores del estado SQL confirmado.
Los eventos de control usan la hora UTC de la aplicación. `demo_error` lleva
un mensaje público fijo; no incluye excepciones, SQL ni credenciales.
No se presenta un movimiento como exitoso si falla su actualización o commit.
Los errores detienen los pasos posteriores y liberan la tarea activa.

El manager mantiene una reserva/tarea por `id_vehiculo`, con sincronización de
inicio y limpieza. Una segunda DEMO del mismo vehículo devuelve 409, incluso
durante la validación. Otros vehículos pueden ejecutarse simultáneamente.
Todos los suscriptores del vehículo reciben sus eventos; los de otros vehículos
quedan aislados. La ausencia o desconexión de clientes no detiene la DEMO;
un fallo de entrega no revierte persistencia ni afecta a los demás clientes.

POST `.../cancelar`, con `X-API-Key` y sin cuerpo, interrumpe las esperas de duración/pausa y evita
iniciar más pasos. Si una operación MySQL ya está en curso, se señala cancelación
cooperativa antes de actualizar y antes del commit cuando todavía es posible;
se espera a su rollback/cierre o al cierre de un commit que ya haya empezado.
Cancelar un await no puede detener físicamente el driver síncrono: por eso el
vehículo se libera **después de recoger esa operación**, sin hilos/tareas de
transacción abandonados. No se emiten movimientos posteriores a la cancelación
ni se inventa una orden DETENER. Lo ya confirmado permanece en RDS.

Se publica `demo_cancelada` y la respuesta es:

```json
{"id_vehiculo":1,"id_demo":1,"estado":"cancelada"}
```

Tras responder puede iniciarse otra DEMO. Sin esa ejecución activa se devuelve
404. La finalización, cancelación y error tienen un único resultado terminal.
Al apagar la aplicación se recogen primero las tareas y después se cierran
los clientes WebSocket. El manager es local a un proceso: esta etapa usa una
instancia de Uvicorn, sin coordinación distribuida ni reanudación tras reinicio.

Durante la implementación de la etapa 6 las escrituras y ejecuciones se
verificaron mediante fakes. Las pruebas funcionales posteriores de 2.5 se
resumen al final; la guía EC2 prepara los escenarios públicos de 2.6.

### DETENER y prioridad de cancelación

DETENER es un comando ya existente del catálogo. Para utilizarlo se consulta
GET `/vehiculos/{id_vehiculo}/comandos`, se identifica su fila y se toma su
`id_comando` real. Se envía ese ID mediante el mismo POST
`/vehiculos/{id_vehiculo}/movimientos`, con `X-API-Key`; no existe un ID fijo
de DETENER para todos los vehículos ni se crea un comando nuevo.

Si hay una DEMO activa, primero se solicita POST
`/vehiculos/{id_vehiculo}/demos/{id_demo}/cancelar` y se espera su **200**.
Esa respuesta confirma que la tarea y cualquier operación MySQL en curso se
recogieron y que el vehículo quedó liberado. No iniciar otra secuencia antes
de completar esta cancelación.

Sólo si el usuario solicita explícitamente un movimiento DETENER se envía
después el POST individual con el ID leído del catálogo. Ese movimiento sí
registra una fila individual con `origen="API"`. La cancelación por sí sola
no actualiza estado a un comando supuesto, no llama `sp_registrar_historial`
y no añade un DETENER al historial. Es una cancelación lógica; todavía no
representa una parada física del ESP8266.

## Manejo de errores

La configuración con tipos o rangos inválidos impide el arranque; revisar la
variable señalada. GET `/` no tiene operaciones de base de datos.
Una ruta no registrada devuelve 404. Si el puerto 8000 está ocupado, detener la
instancia anterior antes de volver a iniciar el servidor.

La infraestructura convierte errores del driver en `DatabaseConfigurationError`,
`DatabaseUnavailableError`, `DatabaseTransactionError`,
`StoredProcedureExecutionError`, `DatabaseConflictError` o `DatabaseResultError`,
todos derivados de `DatabaseError`, sin incluir
valores de conexión, parámetros SQL ni mensajes originales. El diagnóstico
traduce estos fallos a 503 con un detalle público fijo. GET `/` puede seguir
respondiendo aunque RDS no esté disponible.

Los códigos se utilizan según el flujo; no se fuerzan respuestas que no
corresponden a una operación:

- 200: consulta, actualización, movimiento individual confirmado o cancelación.
- 201: creación de un recurso de catálogo.
- 202: DEMO validada y aceptada para ejecución asíncrona; no acredita finalización.
- 204: eliminación exitosa, sin cuerpo.
- 401: falta `X-API-Key` en una operación protegida, con autorización configurada.
- 403: header proporcionado pero incorrecto, vacío o duplicado.
- 422: entrada inválida, campos adicionales o IDs fuera de rango.
- 404: vehículo inexistente o comando que no pertenece al vehículo indicado.
- 409: duplicado MySQL (1062), conflicto de referencia (1451/1452) o vehículo/
  comando inactivo al solicitar un movimiento (`ResourceConflictError`).
- 503: autorización sin clave utilizable, configuración/conexión no disponible,
  desconexión durante el SP o fallo al completar la transacción.
- 500: fallo de procedimiento o estructura de resultados inesperada.

Los manejadores de `app/errors/handlers.py` devuelven únicamente `detail` con
un mensaje público. Las filas que no se ajustan al modelo se rechazan dentro de
la transacción, antes de confirmar una escritura. Las colecciones válidas
vacías son listas vacías con 200. La dependencia reutilizable
`app/security/api_key.py` gestiona la autorización sin repetir comprobaciones
en cada handler. Los rechazos de seguridad tampoco revelan credenciales.

## Verificación de lectura y pruebas automatizadas

Con el servidor activo:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/
Invoke-RestMethod -Uri http://localhost:8000/health/database
$vehiculos = @(Invoke-RestMethod -Uri http://localhost:8000/vehiculos)
if ($vehiculos.Count -gt 0) {
    $idVerificado = $vehiculos[0].id_vehiculo
    Invoke-RestMethod -Uri "http://localhost:8000/vehiculos/$idVerificado"
    Invoke-RestMethod -Uri "http://localhost:8000/vehiculos/$idVerificado/comandos"
    Invoke-RestMethod -Uri "http://localhost:8000/vehiculos/$idVerificado/estado"
    Invoke-RestMethod -Uri "http://localhost:8000/vehiculos/$idVerificado/historial"
    $demosLeidas = @(Invoke-RestMethod -Uri "http://localhost:8000/vehiculos/$idVerificado/demos")
    if ($demosLeidas.Count -gt 0) {
        $idDemoLeida = $demosLeidas[0].id_demo
        Invoke-RestMethod -Uri "http://localhost:8000/vehiculos/$idVerificado/demos/$idDemoLeida/movimientos"
    }
}
(Invoke-WebRequest -Uri http://localhost:8000/docs).StatusCode
(Invoke-RestMethod -Uri http://localhost:8000/openapi.json).info.title
git check-ignore .env .venv app/__pycache__
git status --short --branch
```

En Swagger se muestran Salud, Vehículos, Comandos, Estado, Historial,
Movimientos y DEMO, con modelos de solicitud/respuesta, parámetros y los SP de cada
operación. La descripción del POST documenta explícitamente la transacción de
estado más historial, con un solo commit y rollback conjunto. Para esta
comprobación real usar **Try it out** → **Execute** sólo en los GET. Se puede
revisar **Authorize / LocalApiKey** sin enviar una operación protegida. El ID debe
tomarse del listado existente, sin suponerlo. Se verifican listado de vehículos,
detalle de uno existente, sus comandos, estado e historial contra RDS, además
de salud y Swagger. No se ejecuta el POST real ni se insertan, actualizan o
eliminan registros. Tampoco se inicia todavía Thunder Client.

Pruebas automatizadas de infraestructura, modelos, repositorios, servicios y
HTTP, sin RDS ni credenciales reales. Instalar las dependencias de desarrollo
para ejecutar la suite completa con pytest:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Estas pruebas simulan conexiones y cursores para verificar commit/rollback,
limpieza, drenado de resultados, orden de parámetros, validaciones, creación,
PUT completo, eliminación, pertenencia, colecciones vacías y errores. Las
pruebas HTTP usan ASGI y datos ficticios. Pytest se mantiene en
`requirements-dev.txt`; no es una dependencia de ejecución de la API.
Las pruebas de movimiento utilizan el gestor `MySQLDatabase`, el ejecutor y
repositorios reales con una conexión/cursores simulados y snapshots para
verificar commit único, rollback de ambas escrituras, fallo durante drenado,
relectura o commit y conservación de conectado. No ejecutan escrituras en RDS.

### Evidencia histórica de la etapa 5

En la etapa 5 pasaron **226 pruebas: 174 anteriores y 52 nuevas** de
WebSocket y publicación después del commit. Se comprueban suscripciones ASGI, modelos,
clientes simultáneos, aislamiento por vehículo, desconexión/reconexión, timeouts,
limpieza y entrega inicial sin escrituras. Las pruebas POST + WebSocket usan
el servicio y transacciones simuladas: observan commit y cierre antes del envío,
ningún evento tras rollback y éxito HTTP aunque falle un cliente o no haya ninguno.

La comprobación real de la etapa 5 devolvió 200 en GET `/`, `/health/database`,
`/docs`, `/openapi.json` y `/vehiculos/1/estado`. Swagger cargó su interfaz con
versión 0.5.0 y todos los tags HTTP. Una conexión real a
`ws://localhost:8000/ws/vehiculos/1` recibió `estado_actual` desde RDS, cuyo
campo `estado` coincidió exactamente con el GET:

```json
{
  "id_vehiculo": 1,
  "vehiculo": "Mini RC Forklift IoT",
  "id_comando": 1,
  "comando": "DETENER",
  "codigo": 0,
  "conectado": true,
  "fecha_actualizacion": "2026-10-06T23:54:43"
}
```

Se consultó el historial antes y después de abrir/cerrar el WebSocket: los
**cinco registros WORKBENCH permanecieron idénticos**, sin filtros de origen.
**No se ejecutó el POST real de movimiento.** El historial se conserva para la
evidencia antes/después de Thunder Client.
Las comprobaciones de esta etapa no sustituyen las pruebas funcionales
posteriores en Thunder Client.

## Verificación de la etapa 6

Resultado final: **306 pruebas aprobadas: 226 anteriores y 80 nuevas**.
De las nuevas, 46 cubren CRUD, 22 la preparación/transacción por paso, 11 el
manager y sus endpoints, y una la cancelación de envíos encolados en WebSocket.

Las pruebas nuevas de CRUD cubren los ocho endpoints, SP y parámetros reales,
pertenencia, validación, conflictos de orden, relecturas y rollback. Las de datos
de ejecución usan la fábrica de transacciones, ejecutor y repositorios reales
con conexiones simuladas; rechazan cualquier llamada al historial. Las del
manager usan servicios síncronos ficticios, WebSocket real en memoria y sleeps
controlados: no esperan los segundos de la DEMO real.

Se comprueban eventos después del commit/cierre, N pasos dinámicos, las dos
esperas por paso, respuesta 202 sin esperar la secuencia, carreras de inicio,
cancelación, tareas recogidas y clientes aislados o fallidos. Las 226 pruebas
anteriores se conservan sin modificación.

La lectura real de esta etapa devolvió 200 en salud, diagnóstico RDS, Swagger,
OpenAPI y los nuevos GET. La aplicación anuncia versión **0.6.0** y diez
operaciones HTTP bajo DEMO. GET `/vehiculos/1/demos` devolvió una DEMO activa,
ID 1, **Demo programada**. Su GET de movimientos devolvió:

| Orden | Comando | Código | Duración ms | Pausa ms |
| --- | --- | --- | --- | --- |
| 1 | DETENER | 0 | 0 | 700 |
| 2 | AVANZAR | 1 | 3000 | 700 |
| 3 | AVANZAR_DERECHA | 9 | 5000 | 1000 |
| 4 | RETROCEDER_IZQUIERDA | 6 | 5000 | 700 |
| 5 | CLAXON | 128 | 500 | 0 |
| 6 | DETENER | 0 | 0 | 0 |

Estos son datos observados en RDS, **no una secuencia implementada en Python**.
Se cotejaron los JSON de ambos GET con llamadas reales a `sp_obtener_demos` y
`sp_obtener_movimientos_demo` en una transacción READ ONLY: coincidieron.
Antes y después se comprobaron estado e historial: el estado permaneció igual
y los cinco registros WORKBENCH fueron idénticos. No se creó, modificó, eliminó
ni ejecutó ninguna DEMO; tampoco se ejecutó el POST individual real.

La [auditoría de los 21 SP](docs/auditoria_sp.md) muestra repositorio, servicio y
endpoint/flujo para cada procedimiento. Esto acredita la integración de código
y pruebas aisladas; la ejecución real y las pruebas funcionales oficiales
quedaron pendientes para una etapa posterior.

## Verificación de la etapa 7

Resultado: **326 pruebas aprobadas: 306 anteriores y 20 nuevas**. Las nuevas
incluyen diez pruebas de seguridad y diez de auditoría HTTP/OpenAPI. Se
verifican los siete endpoints protegidos, 401/403/503, ausencia de filtración
en errores, acceso público de lectura y esquema `LocalApiKey`. La regresión
usa conexiones y servicios simulados, sin escrituras reales en RDS.

Las comprobaciones reales de lectura devolvieron 200:

| Lectura | Resultado observado |
| --- | --- |
| GET `/` y `/health/database` | Proceso y lectura RDS disponibles |
| GET `/vehiculos` y `/vehiculos/1` | Vehículo 1: Mini RC Forklift IoT |
| GET `/vehiculos/1/comandos` | 11 comandos; DETENER identificado en su catálogo real |
| GET `/vehiculos/1/estado` | Estado sin cambios |
| GET `/vehiculos/1/historial` | Los cinco registros permanecen idénticos |
| GET `/vehiculos/1/demos` | Una DEMO activa: ID 1, Demo programada |
| GET `/vehiculos/1/demos/1/movimientos` | Seis movimientos intactos |
| GET `/docs` y `/openapi.json` | Versión 0.7.0 y esquema de seguridad |

Swagger mostró **Authorize / LocalApiKey** y los candados de las siete
operaciones protegidas. `pip check` no encontró dependencias incompatibles;
`requirements.txt` y `.gitignore` conservaron su contenido auditado. Las
auditorías de [HTTP](docs/auditoria_http.md) y [los 21 SP](docs/auditoria_sp.md)
documentan la correspondencia con los flujos reales.

La API key privada se configuró sólo en `.env`, sin mostrarla. Durante esta
etapa no se ejecutó movimiento individual, DEMO, DELETE, PUT ni creación real.
El historial y la configuración de DEMO permanecen conservados para las
evidencias oficiales. La auditoría final no detectó exposición de secretos en
archivos ni en el historial local de Git. `.env`, `.venv`, cachés y temporales
siguen excluidos; código y README permanecen incluidos. El commit se conserva
localmente, sin push ni despliegue.

## Pruebas funcionales de la práctica 2.5

Estado: **las tres pruebas funcionales fueron completadas**. La guía de
[preparación de las pruebas](docs/pruebas_funcionales.md) se conserva como
referencia de las solicitudes y los criterios utilizados.

Las solicitudes HTTP se realizaron con Thunder Client. El WebSocket de la DEMO
se verificó con Postman, porque esa función requería un plan de pago en la
versión gratuita instalada de Thunder Client.

| Prueba | Solicitud principal | Comprobación |
| --- | --- | --- |
| 1 | POST `/vehiculos/{id_vehiculo}/movimientos`, con `X-API-Key` | 200, estado correcto y un nuevo registro individual API |
| 2 | GET `/vehiculos/{id_vehiculo}/historial`, público | Hasta diez registros, orden descendente y sin borrar los anteriores |
| 3 | `ws://localhost:8000/ws/vehiculos/{id_vehiculo}` + POST `/vehiculos/{id_vehiculo}/demos/{id_demo}/ejecutar`, con `X-API-Key` en el POST | Estado inicial, inicio, N movimientos ordenados, finalización y mismo historial antes/después |

El POST de inicio forma parte de la tercera prueba. No representa una cuarta
prueba. La API key se introduce sólo en la interfaz local y no se muestra en
evidencias ni exportaciones. La secuencia e IDs se obtienen de los GET reales.

Para la práctica 2.6 se documentan HTTPS, dos clientes WSS simultáneos,
persistencia y DEMO mediante Postman en la [guía del examen](docs/despliegue_ec2.md).
Esa guía contiene criterios de comprobación y no acredita nuevas ejecuciones
contra el servidor público.

## Git

Revisar `git status` y el contenido preparado antes de cada commit. El repositorio
publica únicamente código fuente, pruebas y documentación; `.env`, `.venv` y los
secretos permanecen excluidos. Publicar el código no despliega la API: la
instalación en EC2 requiere seguir la guía del servidor y crear sus tareas.

Referencias técnicas: [FastAPI y Uvicorn](https://fastapi.tiangolo.com/deployment/manually/),
[configuración de Pydantic](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) y
[cursores PyMySQL](https://pymysql.readthedocs.io/en/latest/modules/cursors.html).
Certificados: [TLS y CA de Amazon RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html).
