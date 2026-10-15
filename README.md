# Vehículo IoT API — entorno Dev

Práctica 2.5 de Implementación de Soluciones I. API con Python, FastAPI,
Pydantic y una arquitectura por capas, preparada para utilizar los Stored
Procedures de Amazon RDS MySQL. La API se ejecuta localmente en
<http://localhost:8000>; la infraestructura remota prevista se limita a RDS.

## Estado al terminar la sexta etapa

Implementado: configuración mediante variables de entorno, modelo Pydantic de
salud, router independiente, punto de entrada mínimo, Swagger UI, conexión a RDS,
gestión de transacciones, ejecución reutilizable de Stored Procedures y los
catálogos HTTP completos de Vehículos y Comandos. También están implementados
la consulta de estado, la consulta de historial y el movimiento individual
con actualización de estado y registro de historial atómicos. El WebSocket
por vehículo envía el estado inicial desde RDS y difunde movimientos confirmados.
También están implementados el CRUD de DEMO y sus movimientos, la ejecución
asíncrona, la cancelación lógica y los cinco eventos de ejecución por WebSocket.
El arranque y GET `/` no abren conexiones a RDS. GET `/health/database` sí abre
una conexión y ejecuta exclusivamente un SP de lectura.

Se utilizan funcionalmente los **21 SP existentes**, conservando su definición
SQL; ver [auditoría de integración](docs/auditoria_sp.md). Pendiente de etapas posteriores:
autenticación/autorización. No se controla hardware físico.
En esta etapa, las comprobaciones reales contra RDS son exclusivamente de
lectura; la Prueba Funcional 1 de movimiento real queda pendiente.

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
etapa 1, sin agregar dependencias en esta etapa. La conexión real se verificó
con Python 3.14.8.

## Configuración local

Crear `.env` a partir del ejemplo sólo si aún no existe:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

| Variable | Uso | Valor inicial |
| --- | --- | --- |
| `APP_NAME` | Nombre mostrado en Swagger y salud | Vehículo IoT API |
| `APP_ENV` | Entorno permitido en esta práctica | development |
| `DB_HOST` | Endpoint real de RDS | Vacío |
| `DB_PORT` | Puerto MySQL, entre 1 y 65535 | 3306 |
| `DB_NAME` | Base de datos existente | vehiculo_iot |
| `DB_USER` | Usuario real de RDS | Vacío |
| `DB_PASSWORD` | Contraseña real de RDS | Vacío |
| `DB_SSL_CA` | CA pública de RDS, ruta absoluta o relativa al proyecto | .certs/rds-global-bundle.pem |
| `DB_CONNECT_TIMEOUT` | Espera máxima de conexión, segundos (1–60) | 5 |
| `DB_READ_TIMEOUT` | Espera máxima de lectura, segundos (1–120) | 10 |
| `DB_WRITE_TIMEOUT` | Espera máxima de escritura, segundos (1–120) | 10 |

La clase `Settings` lee `.env` desde la raíz del proyecto y valida sus valores.
Las variables del proceso tienen prioridad sobre el archivo. La contraseña usa
`SecretStr` y no se devuelve en las respuestas. Las credenciales vacías permiten
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

## Ejecutar FastAPI localmente

Desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

El servidor escucha en la interfaz local. Detenerlo con `Ctrl+C`.

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

```json
{"id_comando": 1}
```

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

Se conservan todas las carpetas iniciales y se incorpora `app/errors/`.

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
│   └── handlers.py       # Traducción HTTP 404/409/500/503
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

Los tags Salud, Vehículos, Comandos, Estado, Historial y Movimientos están
disponibles en Swagger. WebSocket se documenta a continuación porque OpenAPI
no representa una suscripción como un endpoint HTTP convencional.

## WebSocket por vehículo

URL exacta: **`ws://localhost:8000/ws/vehiculos/{id_vehiculo}`**.
Ejemplo de lectura: `ws://localhost:8000/ws/vehiculos/1`.
`id_vehiculo` debe ser un entero positivo de hasta 2147483647.

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
Uvicorn en este entorno local. Reinicios requieren reconectar; los eventos
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

El POST de ejecución no recibe cuerpo. `DemoExecutionService.prepare` consulta
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

POST `.../cancelar`, sin cuerpo, interrumpe las esperas de duración/pausa y evita
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

Durante esta etapa las escrituras y ejecuciones se verifican sólo mediante
fakes. **No ejecutar una DEMO real ni POST, PUT o DELETE contra RDS todavía.**

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

Los catálogos ya utilizan estos códigos:

- 422: entrada inválida, campos adicionales o IDs fuera de rango.
- 404: vehículo inexistente o comando que no pertenece al vehículo indicado.
- 409: duplicado MySQL (1062), conflicto de referencia (1451/1452) o vehículo/
  comando inactivo al solicitar un movimiento (`ResourceConflictError`).
- 503: configuración/conexión no disponible, desconexión durante el SP o fallo
  al completar la transacción.
- 500: fallo de procedimiento o estructura de resultados inesperada.

Los manejadores de `app/errors/handlers.py` devuelven únicamente `detail` con
un mensaje público. Las filas que no se ajustan al modelo se rechazan dentro de
la transacción, antes de confirmar una escritura. Las colecciones válidas
vacías son listas vacías con 200. Autenticación/autorización queda pendiente.

## Comprobaciones de esta etapa

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
}
(Invoke-WebRequest -Uri http://localhost:8000/docs).StatusCode
(Invoke-RestMethod -Uri http://localhost:8000/openapi.json).info.title
git check-ignore .env .venv app/__pycache__
git status --short --branch
```

En Swagger se muestran Salud, Vehículos, Comandos, Estado, Historial y
Movimientos, con modelos de solicitud/respuesta, parámetros y los SP de cada
operación. La descripción del POST documenta explícitamente la transacción de
estado más historial, con un solo commit y rollback conjunto. Para esta
comprobación real usar **Try it out** → **Execute** sólo en los GET. El ID debe
tomarse del listado existente, sin suponerlo. Se verifican listado de vehículos,
detalle de uno existente, sus comandos, estado e historial contra RDS, además
de salud y Swagger. No se ejecuta el POST real ni se insertan, actualizan o
eliminan registros. Tampoco se inicia todavía Thunder Client.

Pruebas automatizadas de infraestructura, modelos, repositorios, servicios y
HTTP, sin RDS ni credenciales reales:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Estas pruebas simulan conexiones y cursores para verificar commit/rollback,
limpieza, drenado de resultados, orden de parámetros, validaciones, creación,
PUT completo, eliminación, pertenencia, colecciones vacías y errores. Las
pruebas HTTP usan ASGI y datos ficticios, sin agregar dependencias de pruebas.
Las pruebas de movimiento utilizan el gestor `MySQLDatabase`, el ejecutor y
repositorios reales con una conexión/cursores simulados y snapshots para
verificar commit único, rollback de ambas escrituras, fallo durante drenado,
relectura o commit y conservación de conectado. No ejecutan escrituras en RDS.

En la etapa 5 pasaron **226 pruebas: 174 anteriores y 52 nuevas** de
WebSocket y publicación después del commit. Se comprueban suscripciones ASGI, modelos,
clientes simultáneos, aislamiento por vehículo, desconexión/reconexión, timeouts,
limpieza y entrega inicial sin escrituras. Las pruebas POST + WebSocket usan
el servicio y transacciones simuladas: observan commit y cierre antes del envío,
ningún evento tras rollback y éxito HTTP aunque falle un cliente o no haya ninguno.

La comprobación real de esta etapa devolvió 200 en GET `/`, `/health/database`,
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
siguen pendientes.

## Git

Revisar `git status` y el contenido preparado antes de cada commit. Mantener
commits locales pequeños y descriptivos. No realizar push ni publicar o
desplegar la API durante esta etapa.

Referencias técnicas: [FastAPI y Uvicorn](https://fastapi.tiangolo.com/deployment/manually/),
[configuración de Pydantic](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) y
[cursores PyMySQL](https://pymysql.readthedocs.io/en/latest/modules/cursors.html).
Certificados: [TLS y CA de Amazon RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html).
