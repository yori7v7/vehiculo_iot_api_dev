# Vehículo IoT API — entorno Dev

Práctica 2.5 de Implementación de Soluciones I. API con Python, FastAPI,
Pydantic y una arquitectura por capas, preparada para utilizar los Stored
Procedures de Amazon RDS MySQL. La API se ejecuta localmente en
<http://localhost:8000>; la infraestructura remota prevista se limita a RDS.

## Estado al terminar la tercera etapa

Implementado: configuración mediante variables de entorno, modelo Pydantic de
salud, router independiente, punto de entrada mínimo, Swagger UI, conexión a RDS,
gestión de transacciones, ejecución reutilizable de Stored Procedures y los
catálogos HTTP completos de Vehículos y Comandos.
El arranque y GET `/` no abren conexiones a RDS. GET `/health/database` sí abre
una conexión y ejecuta exclusivamente un SP de lectura.

Se utilizan los cinco SP de Vehículos y los cuatro de Comandos, conservando su
definición SQL. Pendiente de etapas posteriores: movimiento individual, estado,
historial, DEMO, WebSocket y autenticación/autorización. No se controla hardware
físico ni se ejecutan todavía los demás flujos de los 21 procedimientos.

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
│   └── commands.py       # CommandCreate/Update/Response
├── repositories/
│   ├── base.py           # Validación de filas e IDs devueltos por SP
│   ├── vehicles.py       # Los cinco SP de Vehículos
│   └── commands.py       # Los cuatro SP de Comandos
├── routers/
│   ├── health.py         # Salud HTTP y diagnóstico RDS
│   ├── vehicles.py       # CRUD de vehículos
│   └── commands.py       # Comandos por vehículo
├── services/
│   ├── database_health.py # Lectura segura con sp_obtener_vehiculos
│   ├── vehicles.py       # Existencia y transacciones de vehículos
│   └── commands.py       # Padre, pertenencia y transacciones de comandos
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

Los servicios de catálogos ya coordinan sus transacciones. Movimiento individual deberá
actualizar estado y registrar historial en una misma conexión y transacción,
con rollback ante fallos y emisión WebSocket únicamente después del commit.
El servicio DEMO tendrá su propia coordinación asíncrona y no registrará
historial individual. Estos flujos de negocio aún no están implementados.

## Fuente de verdad y próximos módulos

El archivo proporcionado `vehiculo_iot_rds.sql`, actualmente externo al
repositorio, define las seis tablas y los 21 Stored Procedures existentes de
`vehiculo_iot`. Debe consultarse antes de implementar acceso a datos; no ejecutar
el script para arrancar esta API ni alterar la estructura de RDS.

Los tags Vehículos y Comandos ya están disponibles en Swagger. Los futuros
routers de Estado, Historial y DEMO se concretarán en etapas posteriores con el
SQL como referencia, al igual que el movimiento individual y el WebSocket.

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
- 409: duplicado MySQL (1062) o conflicto de referencia (1451/1452).
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
}
(Invoke-WebRequest -Uri http://localhost:8000/docs).StatusCode
(Invoke-RestMethod -Uri http://localhost:8000/openapi.json).info.title
git check-ignore .env .venv app/__pycache__
git status --short --branch
```

En Swagger se muestran Salud, Vehículos y Comandos, con modelos de creación,
actualización y respuesta, parámetros y los SP de cada operación. Para esta
comprobación real usar **Try it out** → **Execute** sólo en los GET. El ID debe
tomarse del listado existente, sin suponerlo. Se verifican listado de vehículos,
detalle de uno existente y sus comandos contra RDS, además de salud y Swagger.
No se insertan, actualizan ni eliminan registros.

Pruebas automatizadas de infraestructura, modelos, repositorios, servicios y
HTTP, sin RDS ni credenciales reales:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Estas pruebas simulan conexiones y cursores para verificar commit/rollback,
limpieza, drenado de resultados, orden de parámetros, validaciones, creación,
PUT completo, eliminación, pertenencia, colecciones vacías y errores. Las
pruebas HTTP usan ASGI y datos ficticios, sin agregar dependencias de pruebas.
No ejecutan escrituras reales en RDS.
Al cierre de la etapa 3 pasaron **107 pruebas**. La comprobación real devolvió
200 para salud, diagnóstico RDS, listado de vehículos (1 registro), detalle del
vehículo 1 y sus comandos (11 registros ordenados por código y con el mismo
`id_vehiculo`). Swagger mostró las nueve operaciones nuevas bajo Vehículos y
Comandos. La verificación real utilizó exclusivamente GET.
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
