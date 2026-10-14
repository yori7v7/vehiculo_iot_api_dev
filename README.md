# Vehículo IoT API — entorno Dev

Práctica 2.5 de Implementación de Soluciones I. API con Python, FastAPI,
Pydantic y una arquitectura por capas, preparada para utilizar los Stored
Procedures de Amazon RDS MySQL. La API se ejecuta localmente en
<http://localhost:8000>; la infraestructura remota prevista se limita a RDS.

## Estado de la primera etapa

Implementado: configuración mediante variables de entorno, modelo Pydantic de
salud, router independiente, punto de entrada mínimo y Swagger UI.
El arranque y la consulta de salud no abren conexiones a RDS.

Pendiente de etapas posteriores: acceso a datos, operaciones de vehículos y
comandos, movimiento individual, historial, DEMO, WebSocket y autorización de
operaciones sensibles. No se controla todavía hardware físico.

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
instalado para la futura conexión MySQL; esta etapa no utiliza el cliente.

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

La clase `Settings` lee `.env` desde la raíz del proyecto y valida sus valores.
Las variables del proceso tienen prioridad sobre el archivo. La contraseña usa
`SecretStr` y no se devuelve en las respuestas. Las credenciales vacías permiten
verificar FastAPI en esta etapa; no prueban conectividad con RDS. Reiniciar el
servidor después de editar `.env`, ya que la configuración se carga una vez por
proceso.

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
- Swagger UI: <http://localhost:8000/docs>
- Esquema OpenAPI: <http://localhost:8000/openapi.json>

## Endpoint disponible

| Método | Ruta | Propósito | Respuesta | Stored Procedure |
| --- | --- | --- | --- | --- |
| GET | `/` | Comprobar que FastAPI responde | 200, `HealthResponse` | Ninguno |

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

## Arquitectura

Se conservan todas las carpetas iniciales y se incorpora `app/errors/`.

```text
app/
├── config/
│   └── settings.py       # Clase Settings y carga del entorno
├── database/             # Conexión, transacciones y ejecutor de SP, pendientes
├── errors/               # Errores de dominio y manejadores HTTP, pendientes
├── models/
│   └── health.py         # Modelo HealthResponse
├── repositories/         # Acceso a datos por entidad, pendiente
├── routers/
│   └── health.py         # Endpoint de salud
├── services/             # Reglas de negocio y ejecución asíncrona de DEMO, pendientes
├── websocket/            # Conexiones y difusión por vehículo, pendientes
└── main.py               # Construcción de FastAPI y registro de routers
```

Flujo previsto: cliente HTTP → router → servicio → repositorio → ejecutor de
Stored Procedures → conexión a RDS. Los servicios se comunicarán con el gestor
WebSocket para distribuir eventos por vehículo. La conexión, el ejecutor,
los repositorios, los servicios y el gestor serán clases con responsabilidades
separadas. `main.py` seguirá siendo el punto de composición.

Los servicios coordinarán las transacciones. Movimiento individual deberá
actualizar estado y registrar historial en una misma conexión y transacción,
con rollback ante fallos y emisión WebSocket únicamente después del commit.
El servicio DEMO tendrá su propia coordinación asíncrona y no registrará
historial individual. Estas capas están reservadas, aún sin implementación.

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

La configuración inválida impide el arranque; revisar el nombre y rango de la
variable señalada. El endpoint de salud no tiene operaciones de base de datos.
Una ruta no registrada devuelve 404. Si el puerto 8000 está ocupado, detener la
instancia anterior antes de volver a iniciar el servidor.

En las próximas etapas, `app/errors/` centralizará la traducción de errores:
validación de entrada (422), recurso inexistente (404), conflicto (409), servicio
no disponible (503) y fallos internos (500), según cada operación. Las
colecciones válidas vacías se devolverán como listas vacías. Autorización y
otros códigos se incorporarán sólo cuando el flujo implementado los requiera.

## Comprobaciones de esta etapa

Con el servidor activo:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/
(Invoke-WebRequest -Uri http://localhost:8000/docs).StatusCode
(Invoke-RestMethod -Uri http://localhost:8000/openapi.json).info.title
git check-ignore .env .venv app/__pycache__
git status --short --branch
```

En Swagger, abrir el tag Salud, expandir GET `/`, pulsar **Try it out** y
**Execute**. Debe devolver 200 y el JSON mostrado. Estas comprobaciones de
arranque no sustituyen las tres pruebas funcionales posteriores en Thunder
Client:

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
[PyMySQL](https://github.com/PyMySQL/PyMySQL).
