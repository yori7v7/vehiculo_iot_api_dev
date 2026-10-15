# Vehículo IoT API — entorno Dev

Práctica 2.5 de Implementación de Soluciones I. API con Python, FastAPI,
Pydantic y una arquitectura por capas, preparada para utilizar los Stored
Procedures de Amazon RDS MySQL. La API se ejecuta localmente en
<http://localhost:8000>; la infraestructura remota prevista se limita a RDS.

## Estado al terminar la segunda etapa

Implementado: configuración mediante variables de entorno, modelo Pydantic de
salud, router independiente, punto de entrada mínimo, Swagger UI, conexión a RDS,
gestión de transacciones y ejecución reutilizable de Stored Procedures.
El arranque y GET `/` no abren conexiones a RDS. GET `/health/database` sí abre
una conexión y ejecuta exclusivamente un SP de lectura.

Pendiente de etapas posteriores: repositorios y operaciones de vehículos y
comandos, movimiento individual, historial, DEMO, WebSocket y autorización de
operaciones sensibles. No se controla todavía hardware físico ni se implementan
individualmente los 21 procedimientos.

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

No requiere parámetros ni cuerpo. Con la configuración inicial responde:

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
│   └── database.py       # Excepciones controlables sin datos sensibles
├── models/
│   └── health.py         # Modelos de salud HTTP, salud RDS y error de diagnóstico
├── repositories/         # Acceso a datos por entidad, pendiente
├── routers/
│   └── health.py         # Salud HTTP y diagnóstico RDS
├── services/
│   └── database_health.py # Lectura segura con sp_obtener_vehiculos
├── websocket/            # Conexiones y difusión por vehículo, pendientes
└── main.py               # Construcción de FastAPI y registro de routers
```

Flujo previsto: cliente HTTP → router → servicio → repositorio → ejecutor de
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

Los servicios coordinarán las transacciones. Movimiento individual deberá
actualizar estado y registrar historial en una misma conexión y transacción,
con rollback ante fallos y emisión WebSocket únicamente después del commit.
El servicio DEMO tendrá su propia coordinación asíncrona y no registrará
historial individual. Estos flujos de negocio aún no están implementados.

## Fuente de verdad y próximos módulos

El archivo proporcionado `vehiculo_iot_rds.sql`, actualmente externo al
repositorio, define las seis tablas y los 21 Stored Procedures existentes de
`vehiculo_iot`. Debe consultarse antes de implementar acceso a datos; no ejecutar
el script para arrancar esta API ni alterar la estructura de RDS.

Los futuros routers se documentarán en Swagger con los tags Vehículos,
Comandos, Estado, Historial y DEMO. Cubrirán los CRUD solicitados, el movimiento
individual, la consulta de estado, los diez movimientos individuales más
recientes y el inicio/cancelación de una DEMO existente. Sus rutas, modelos y
firmas se concretarán en etapas posteriores con el SQL como referencia.

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
`DatabaseUnavailableError`, `DatabaseTransactionError` o
`StoredProcedureExecutionError`, todos derivados de `DatabaseError`, sin incluir
valores de conexión, parámetros SQL ni mensajes originales. El diagnóstico
traduce estos fallos a 503 con un detalle público fijo. GET `/` puede seguir
respondiendo aunque RDS no esté disponible.

En las próximas etapas se ampliará la traducción de errores:
validación de entrada (422), recurso inexistente (404), conflicto (409), servicio
no disponible (503) y fallos internos (500), según cada operación. Las
colecciones válidas vacías se devolverán como listas vacías. Autorización y
otros códigos se incorporarán sólo cuando el flujo implementado los requiera.

## Comprobaciones de esta etapa

Con el servidor activo:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/
Invoke-RestMethod -Uri http://localhost:8000/health/database
(Invoke-WebRequest -Uri http://localhost:8000/docs).StatusCode
(Invoke-RestMethod -Uri http://localhost:8000/openapi.json).info.title
git check-ignore .env .venv app/__pycache__
git status --short --branch
```

En Swagger, abrir el tag Salud y ejecutar GET `/` y GET `/health/database`
mediante **Try it out** → **Execute**. Deben devolver 200 y sus JSON mostrados.
La prueba real de la segunda etapa utilizó `sp_obtener_vehiculos()` en modo
`READ ONLY`, terminó con rollback y produjo la respuesta de disponibilidad.
No se insertaron, actualizaron ni eliminaron registros.

Pruebas unitarias de infraestructura, sin RDS ni credenciales reales:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Estas pruebas simulan conexiones y cursores para verificar commit/rollback,
limpieza, drenado de resultados y errores. No prueban escrituras reales en RDS.
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
