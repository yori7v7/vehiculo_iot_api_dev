# Auditoría HTTP y seguridad local

La aplicación expone **24 operaciones HTTP de negocio**: 9 GET, 7 POST,
4 PUT y 4 DELETE. Además dispone de una ruta WebSocket y de las rutas
automáticas de documentación de FastAPI. La matriz refleja el código de la
etapa 5.1 y se comprueba generando OpenAPI con los ocho routers HTTP en una
aplicación aislada, sin importar `app.main`, leer `.env`, abrir sockets ni
consultar RDS.

Se revisaron los routers, servicios, repositorios, ejecutor de SP, errores,
configuración de ejemplo, `.gitignore`, dependencias y
[la auditoría de los 21 SP](auditoria_sp.md). Las escrituras de las pruebas
utilizan datos simulados. Esta auditoría no certifica escrituras en RDS.

## Matriz de operaciones

Abreviaturas de ruta: `V = /vehiculos/{id_vehiculo}`;
`D = V/demos/{id_demo}`; `M = D/movimientos/{id_demo_movimiento}`.
La columna de códigos incluye éxito, errores de validación y errores
controlados documentados. `Clave` indica que se exige `X-API-Key`.

| Método y ruta | Tag | Respuesta de éxito | Códigos HTTP documentados | Clave |
| --- | --- | --- | --- | --- |
| GET `/` | Salud | `HealthResponse` | 200, 500 | No |
| GET `/health/database` | Salud | `DatabaseHealthResponse` | 200, 500, 503 | No |
| GET `/vehiculos` | Vehículos | `list[VehicleResponse]` | 200, 500, 503 | No |
| POST `/vehiculos` | Vehículos | `VehicleResponse` | 201, 401, 403, 422, 500, 503 | Sí |
| GET `V` | Vehículos | `VehicleResponse` | 200, 404, 422, 500, 503 | No |
| PUT `V` | Vehículos | `VehicleResponse` | 200, 401, 403, 404, 422, 500, 503 | Sí |
| DELETE `V` | Vehículos | Sin cuerpo | 204, 401, 403, 404, 409, 422, 500, 503 | Sí |
| POST `V/comandos` | Comandos | `CommandResponse` | 201, 401, 403, 404, 409, 422, 500, 503 | Sí |
| GET `V/comandos` | Comandos | `list[CommandResponse]` | 200, 404, 422, 500, 503 | No |
| PUT `V/comandos/{id_comando}` | Comandos | `CommandResponse` | 200, 401, 403, 404, 409, 422, 500, 503 | Sí |
| DELETE `V/comandos/{id_comando}` | Comandos | Sin cuerpo | 204, 401, 403, 404, 409, 422, 500, 503 | Sí |
| GET `V/estado` | Estado | `StateResponse` o `null` | 200, 404, 422, 500, 503 | No |
| GET `V/historial` | Historial | `list[HistoryResponse]` | 200, 404, 422, 500, 503 | No |
| POST `V/movimientos` | Movimientos | `MovementResponse` | 200, 401, 403, 404, 409, 422, 500, 503 | Sí |
| POST `V/demos` | DEMO | `DemoResponse` | 201, 401, 403, 404, 409, 422, 500, 503 | Sí |
| GET `V/demos` | DEMO | `list[DemoResponse]` | 200, 404, 422, 500, 503 | No |
| PUT `D` | DEMO | `DemoResponse` | 200, 401, 403, 404, 422, 500, 503 | Sí |
| DELETE `D` | DEMO | Sin cuerpo | 204, 401, 403, 404, 422, 500, 503 | Sí |
| POST `D/movimientos` | DEMO | `DemoMovementResponse` | 201, 401, 403, 404, 409, 422, 500, 503 | Sí |
| GET `D/movimientos` | DEMO | `list[DemoMovementResponse]` | 200, 404, 422, 500, 503 | No |
| PUT `M` | DEMO | `DemoMovementResponse` | 200, 401, 403, 404, 409, 422, 500, 503 | Sí |
| DELETE `M` | DEMO | Sin cuerpo | 204, 401, 403, 404, 422, 500, 503 | Sí |
| POST `D/ejecutar` | DEMO | `DemoExecutionResponse` | 202, 401, 403, 404, 409, 422, 500, 503 | Sí |
| POST `D/cancelar` | DEMO | `DemoExecutionResponse` | 200, 401, 403, 404, 422, 500, 503 | Sí |

Las 24 operaciones tienen resumen y descripción. Las 23 que usan SP o
participan en el flujo de cancelación describen esa relación; la cancelación
declara expresamente que carece de SP propio. Los parámetros y cuerpos tienen
esquemas Pydantic. Los cuatro DELETE usan 204 sin contenido ni esquema JSON
de éxito. Las colecciones vacías válidas devuelven 200 con `[]`; un vehículo
existente sin fila de estado devuelve 200 con `null`.

POST `D/ejecutar` devuelve 202 después de preparar y validar el plan. Los
fallos posteriores de la tarea se comunican mediante `demo_error` por
WebSocket. POST `D/cancelar` devuelve 200 cuando se recoge la ejecución y
se libera el vehículo; sus 503 documentados corresponden a la configuración
de autorización, puesto que el endpoint no inicia consultas SQL propias.

## Códigos y modelos de error

| Código | Causa y representación |
| --- | --- |
| 400 | Ningún caso de negocio lo emite actualmente. No se añadió artificialmente a OpenAPI. |
| 401 | Falta `X-API-Key` en una operación protegida. JSON `ErrorResponse` y cabecera `WWW-Authenticate`. |
| 403 | Clave incorrecta, vacía o cabecera duplicada. JSON `ErrorResponse` con mensaje estático. |
| 404 | Recurso o relación solicitada inexistente; en cancelar, ausencia de una ejecución activa de esa DEMO. JSON `ErrorResponse`. |
| 409 | Estado incompatible con la operación, vehículo ocupado durante el inicio de DEMO, orden o campos únicos repetidos, o restricción de integridad aplicable. JSON `ErrorResponse`. |
| 422 | Path o cuerpo inválido según el contrato Pydantic, incluidos JSON inválido, rangos, tipos estrictos y campos adicionales. Esquema `HTTPValidationError` de FastAPI. |
| 500 | SP fallido, resultado inesperado o excepción no prevista. JSON con `detail`; el fallback genérico devuelve siempre `No fue posible procesar la solicitud.` |
| 503 | Configuración/indisponibilidad de MySQL o fallo transaccional; también configuración de API key no utilizable en operaciones protegidas. El diagnóstico de RDS convierte cualquier `DatabaseError` en su 503 público específico. |

El handler central convierte `DatabaseConflictError` en 409;
`DatabaseConfigurationError`, `DatabaseUnavailableError` y
`DatabaseTransactionError` en 503; los demás `DatabaseError` en 500.
`ResourceNotFoundError` y `ResourceConflictError` corresponden a 404 y 409.
Las excepciones del driver se traducen a clases de mensaje público fijo.
El fallback de excepciones inesperadas no devuelve `str(error)`, SQL,
credenciales ni traceback en el cuerpo HTTP.

La tabla de cada endpoint refleja su flujo concreto. Los GET no anuncian
401/403 ni conflictos de escritura. PUT de DEMO, DELETE de DEMO y DELETE de
paso no anuncian 409 por comando inactivo: esas operaciones no comprueban ese
estado. Los conflictos de comandos y orden se documentan al agregar o editar
pasos. La creación de DEMO puede encontrar un conflicto de referencia del
vehículo en MySQL.

FastAPI también devuelve 404 para rutas no existentes y 405 para métodos no
admitidos. Esos resultados de enrutamiento no representan SP nuevos.

## Alcance de la API key

El esquema OpenAPI `LocalApiKey` utiliza una cabecera `X-API-Key` y permite
configurar la clave en el botón **Authorize** de Swagger. Los **15 endpoints
de escritura** exigen `require_api_key`. Incluyen ocho altas o ediciones
administrativas, los cuatro DELETE, el movimiento individual, el inicio y la
cancelación de DEMO. Los **nueve GET**, las rutas de documentación y el
WebSocket de monitoreo siguen siendo públicos.

La revisión de referencia `3792236` encontró siete escrituras protegidas y
ocho POST/PUT administrativos sin la dependencia. La etapa 5.1 aplica la
misma dependencia y declara 401, 403 y 503 en esas ocho rutas. Los contratos de
negocio para solicitudes autorizadas se conservan. La verificación describe el
código de la rama y deja pendiente su despliegue y comprobación en EC2.

La clave configurada es `Settings.api_key: SecretStr` con `repr=False`.
La comparación usa `hmac.compare_digest` sobre bytes UTF-8. La dependencia
rechaza cabeceras duplicadas o vacías; comprueba que la configuración no esté
vacía ni sea `change-me` o `changeme`. Una petición sin cabecera recibe 401;
con cabecera única no vacía y configuración no utilizable recibe 503. Una clave
incorrecta con configuración válida recibe 403. Los errores de autorización
omiten el valor recibido y el configurado. El rechazo impide ejecutar la
operación de negocio.

Introduce la clave privada en **Authorize → LocalApiKey**, sin prefijo
`Bearer`, únicamente en una sesión de confianza. Retírala de la sesión al
terminar y mantenla fuera de URL, cuerpos JSON, capturas, exportaciones y
logs. CORS regula el acceso desde el navegador. La autorización de las
escrituras se valida en FastAPI, incluido el tráfico del mismo origen.

La API key es una credencial compartida de operador. La etapa 5.1 se limita
al endurecimiento de las rutas actuales. El modo temporal para invitados se
describe como propuesta. [Diseño de control público temporal](control_publico_temporal.md)

`.env.example` contiene `API_KEY=change-me`, valor deliberadamente incapaz de
autorizar. No se guardan ejemplos de claves reales. `.gitignore` excluye
`.env`, `.env.*`, certificados/claves locales, `.venv`, cachés y logs;
mantiene la excepción para `.env.example`. Se comprobó con `git check-ignore
--no-index` que `.env`, `.env.local`, `.env.production` y la CA local quedan
excluidos. La auditoría no leyó el contenido de `.env`.

## Relación con los 21 SP

El análisis AST de `app/repositories/*.py` y `app/services/*.py` encontró
22 llamadas a `StoredProcedureExecutor.execute`: **21 nombres distintos**,
todos literales y presentes en el script SQL. La llamada adicional es
`sp_obtener_vehiculos()` del diagnóstico. No hubo nombres desconocidos,
procedimientos sin cobertura ni discrepancias en el número de parámetros.
La relación completa de repositorio, servicio y endpoint se conserva en
[auditoria_sp.md](auditoria_sp.md).

Se contrastaron las firmas y cuerpos del archivo original
`vehiculo_iot_rds.sql`; su SHA-256 en esta revisión fue
`6378091a759ade267ee6e19f7f6dfe4788c3f30ad5f01036c74930b86f25f7d9`.
Los siete procedimientos de lectura contienen SELECT y no contienen DML:

- `sp_obtener_vehiculos`
- `sp_obtener_vehiculo`
- `sp_obtener_comandos_vehiculo`
- `sp_obtener_estado`
- `sp_obtener_historial`
- `sp_obtener_demos`
- `sp_obtener_movimientos_demo`

Las lecturas HTTP y la carga inicial WebSocket usan esos SP dentro de
transacciones READ ONLY. Los otros 14 SP realizan escrituras. No se agregaron
SQL directo, SP de ejecución/cancelación ni getters inexistentes. Esta
comprobación del script es estática; no inspecciona definiciones remotas.

El movimiento individual confirma estado e historial juntos y después
publica el evento. DEMO confirma cada paso por separado, conserva conectado
y no llama `sp_registrar_historial`. Un fallo de entrega WebSocket no revierte
una escritura confirmada. El historial devuelve hasta diez filas existentes
en el orden del SP, sin filtrar `WORKBENCH` ni ningún otro origen.

## WebSocket y documentación

`/ws/vehiculos/{id_vehiculo}` queda fuera de las 24 operaciones HTTP y de
OpenAPI. Valida el identificador y la existencia antes de aceptar. Rechaza
con cierre lógico 1008 un ID inválido o vehículo inexistente, y con 1011 un
fallo interno. Cuando el cierre ocurre antes del handshake, Uvicorn puede
presentarlo al cliente como rechazo HTTP 403. Ese 403 no es una comprobación
de API key. Recibir mensajes del socket no ejecuta comandos ni modifica
`conectado`.

## Correcciones y comprobaciones reproducibles

La auditoría original de la etapa 7 dejó registradas estas correcciones.

- Los 422 manuales de estado e historial no tenían esquema; ahora se genera
  `HTTPValidationError` automáticamente.
- Se documentó 500 en cancelación y en las dos rutas de Salud.
- Se agregó el fallback genérico 500 con JSON estático.
- Se quitaron 409 ajenos al flujo de PUT/DELETE de DEMO y DELETE de paso y se
  precisaron las descripciones de conflicto.
- Se declararon `LocalApiKey` y 401/403/503 con modelos en las siete operaciones que estaban protegidas entonces.

Las dependencias directas continúan fijadas en `requirements.txt`. La API key
utiliza biblioteca estándar y componentes ya disponibles de FastAPI, por lo
que no requiere paquetes adicionales. No se cambiaron versiones ni se afirma
haber realizado una comprobación externa de vulnerabilidades.

Las suites de auditoría y seguridad se pueden ejecutar juntas sin RDS.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_http_audit.py tests/test_security.py tests/test_websocket_route.py -q
```

Estas suites comprueban las 24 operaciones, el esquema y los requisitos de
seguridad de las 15 escrituras, los nueve GET públicos y la suscripción WSS de
lectura. La auditoría de contratos comprueba modelos de errores incluidos 422,
DELETE 204 sin esquema, nombres y aridad de los 21 SP y JSON seguro ante
errores inesperados. Las demás pruebas verifican los flujos de negocio con
dobles. Para ejecutar el conjunto, usa el comando siguiente.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

### Resultado local de la etapa 5.1

La referencia `3792236` registró 332 pruebas aprobadas, tres fallidas y 683 subpruebas aprobadas. Las tres expectativas fallidas de WSS precedían a `id_evento`. Se actualizaron para comprobar el UUID v4 en hexadecimal y conservar las aserciones exactas sobre los demás campos. El emisor y los contratos WSS conservan su implementación.

La rama aprobó **338 pruebas y 787 subpruebas**, con cero fallos. En los ocho POST/PUT administrativos se verificaron 401 sin clave, 403 con clave incorrecta, vacía o duplicada, 503 con configuración no utilizable y 201 o 200 con clave válida. Los rechazos ocurren antes de resolver el servicio. Se verificó la ausencia de la clave ficticia en respuestas y registros capturados durante las pruebas.

La comparación de OpenAPI antes y después confirmó las mismas 24 operaciones, con siete escrituras protegidas en la referencia y 15 en la rama. Los nueve GET, las respuestas de negocio y el esquema de las escrituras autorizadas conservaron sus contratos. Las pruebas usaron ASGI y dobles locales, sin acceso a RDS o al vehículo.
