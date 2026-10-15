# Vehículo IoT API — entorno Dev

Práctica 2.5 de Implementación de Soluciones I. API con Python, FastAPI,
Pydantic y una arquitectura por capas, preparada para utilizar los Stored
Procedures de Amazon RDS MySQL. La API se ejecuta localmente en
<http://localhost:8000>; la infraestructura remota prevista se limita a RDS.

## Estado al terminar la cuarta etapa

Implementado: configuración mediante variables de entorno, modelo Pydantic de
salud, router independiente, punto de entrada mínimo, Swagger UI, conexión a RDS,
gestión de transacciones, ejecución reutilizable de Stored Procedures y los
catálogos HTTP completos de Vehículos y Comandos. También están implementados
la consulta de estado, la consulta de historial y el movimiento individual
con actualización de estado y registro de historial atómicos.
El arranque y GET `/` no abren conexiones a RDS. GET `/health/database` sí abre
una conexión y ejecuta exclusivamente un SP de lectura.

Se utilizan los cinco SP de Vehículos, cuatro de Comandos, dos de Estado y dos
de Historial, conservando su definición SQL. Pendiente de etapas posteriores:
DEMO, WebSocket y autenticación/autorización. No se controla hardware físico.
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
comportamiento de cascadas del esquema; en comandos, referencias de movimientos
de DEMO pueden impedir eliminar y producir 409. Esta etapa implementa y prueba
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
anterior, según confirmó el usuario. La futura ejecución de DEMO deberá evitar
llamar a `sp_registrar_historial`; no se ocultan registros mediante etiquetas.

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
7. Sale del contexto, realiza **un solo commit** y sólo entonces devuelve 200.

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
El origen API es fijo y no lo decide el cliente. No se emiten eventos WebSocket
ni se afirma que el hardware haya ejecutado físicamente la orden.

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
│   └── movement.py       # MovementRequest y MovementResponse
├── repositories/
│   ├── base.py           # Validación de filas e IDs devueltos por SP
│   ├── vehicles.py       # Los cinco SP de Vehículos
│   ├── commands.py       # Los cuatro SP de Comandos
│   ├── state.py          # Obtener/actualizar estado
│   └── history.py        # Consultar/registrar historial
├── routers/
│   ├── health.py         # Salud HTTP y diagnóstico RDS
│   ├── vehicles.py       # CRUD de vehículos
│   ├── commands.py       # Comandos por vehículo
│   ├── state.py          # GET estado
│   ├── history.py        # GET historial
│   └── movement.py       # POST movimiento individual
├── services/
│   ├── database_health.py # Lectura segura con sp_obtener_vehiculos
│   ├── vehicles.py       # Existencia y transacciones de vehículos
│   ├── commands.py       # Padre, pertenencia y transacciones de comandos
│   ├── state.py          # Padre y estado sin escrituras
│   ├── history.py        # Padre y máximo diez, sin filtro de origen
│   └── movement.py       # Reglas y transacción atómica de movimiento
├── websocket/            # Conexiones y difusión por vehículo, pendientes
├── dependencies.py       # Composición de la fábrica de conexiones por solicitud
└── main.py               # Construcción de FastAPI y registro de routers
```

Flujo actual: cliente HTTP → router → servicio → repositorio → ejecutor de
Stored Procedures → conexión a RDS. Los servicios se comunicarán con el gestor
WebSocket para distribuir eventos por vehículo. La conexión, el ejecutor,
los repositorios, los servicios y el gestor tienen o tendrán clases con
responsabilidades separadas. `main.py` sigue siendo el punto de composición.

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

Los servicios de catálogos y movimiento individual ya coordinan sus
transacciones. El futuro WebSocket sólo podrá anunciar éxito después de la
confirmación de la transacción. El servicio DEMO tendrá su propia coordinación
asíncrona y no llamará al registro de historial individual. Esos dos servicios
todavía no están implementados.

## Fuente de verdad y próximos módulos

El archivo proporcionado `vehiculo_iot_rds.sql`, actualmente externo al
repositorio, define las seis tablas y los 21 Stored Procedures existentes de
`vehiculo_iot`. Debe consultarse antes de implementar acceso a datos; no ejecutar
el script para arrancar esta API ni alterar la estructura de RDS.

Los tags Salud, Vehículos, Comandos, Estado, Historial y Movimientos ya están
disponibles en Swagger. DEMO y WebSocket se concretarán en etapas posteriores
con el SQL como referencia.

## WebSocket y DEMO previstos

El servicio WebSocket estará asociado a `id_vehiculo`, admitirá varios clientes
por vehículo y distribuirá sus eventos sólo a esos clientes. La desconexión de
uno no afectará a los demás. No existe todavía una ruta WebSocket disponible.

Los mensajes JSON incluirán `tipo`, `id_vehiculo`, `comando`, `codigo` y
`timestamp`. Para DEMO se utilizarán los eventos `demo_inicio`,
`demo_movimiento`, `demo_fin`, `demo_cancelada` y `error`. El formato definitivo
y los ejemplos con datos válidos se documentarán al implementar el servicio.

Una DEMO existente se iniciará mediante POST; el servicio consultará sus
movimientos por Stored Procedure, respetará `orden`, `duracion_ms` y `pausa_ms`
sin bloquear FastAPI, actualizará estado y permitirá cancelación. Se impedirá
ejecutar dos DEMO simultáneas para el mismo vehículo. No se escribirá en
`historial_comandos` durante su ejecución. El WebSocket representará movimientos,
sin controlar físicamente el ESP8266 en esta práctica.

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
eliminan registros. Tampoco se inicia todavía Thunder Client o una DEMO.

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

Al cierre de la etapa 4 pasaron **174 pruebas** (107 anteriores y 67 nuevas).
La comprobación real devolvió 200 en salud, diagnóstico RDS y los GET nuevos.
El estado real del vehículo 1 quedó leído así, sin modificarlo:

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

`sp_obtener_historial(1)` devolvió **5 registros totales**, todos de origen
`WORKBENCH`; el GET devolvió esos mismos cinco en orden descendente, sin filtro.
El comando confirmado para la futura prueba es ID 1, `DETENER`, código 0,
activo y perteneciente al vehículo 1. **No se ejecutó el POST de movimiento.**
El historial actual se conserva para la evidencia antes/después de Thunder
Client. Swagger mostró las tres operaciones nuevas bajo sus tags respectivos.
Las comprobaciones de esta etapa no sustituyen las tres pruebas funcionales
posteriores en Thunder Client:

1. POST de movimiento individual: respuesta, estado y nuevo historial en RDS.
2. GET de historial: máximo diez, orden descendente y sólo movimientos individuales.
3. WebSocket + DEMO: inicio por POST, movimientos ordenados, tiempos, finalización
   y mismo historial antes y después. El POST de inicio forma parte de esta prueba.

## Git

Revisar `git status` y el contenido preparado antes de cada commit. Mantener
commits locales pequeños y descriptivos. No realizar push ni publicar o
desplegar la API durante esta etapa.

Referencias técnicas: [FastAPI y Uvicorn](https://fastapi.tiangolo.com/deployment/manually/),
[configuración de Pydantic](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) y
[cursores PyMySQL](https://pymysql.readthedocs.io/en/latest/modules/cursors.html).
Certificados: [TLS y CA de Amazon RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html).
