# Vehículo IoT API · Actividad 4.3

API FastAPI para administrar inventario, controlar la unidad asignada y monitorear la grúa IoT. Amazon RDS MySQL conserva el esquema histórico y sus referencias, y registra las entidades de la plataforma 4.3. Caddy expone HTTPS y WSS desde AWS EC2 Windows, con FastAPI en loopback.

[Swagger de producción](https://100-30-4-62.nip.io/docs) · [Portal en GitHub Pages](https://yori7v7.github.io/control-iot-u4/) · [Código del frontend](https://github.com/yori7v7/control-iot-u4) · [Guía técnica 4.3](docs/4.3/README.md)

## Roles y operación

| Rol | Permisos y alcance |
| --- | --- |
| Administrador (ID 1) | Gestiona clientes y accesos, modelos y capacidades, inventario, asignaciones, titularidad, DEMOS de fábrica y reservas. Consulta la auditoría. |
| Comprador (ID 2) | Controla y monitorea la unidad física vendida y asignada, ID 1, serie `RC-IOT-001`. Gestiona DEMOS privadas de su titularidad y puede ejecutar las DEMOS habilitadas de la unidad. |
| Invitado | Usa la unidad lógica de exhibición ID 4, serie `EXH-LOGICA-43`, con reserva exclusiva de 120 segundos, expiración y revocación. El catálogo actual permite DETENER (código 0) y AVANZAR (código 1). La API registra las órdenes con origen `INVITADO` y el invitado recibe eventos de su sesión. |

La única grúa física es una HJ2025-1D con ESP8266 NodeMCU, 74HC595 y ocho PC817. El comprador puede usar las ocho direcciones, DETENER, LUCES, VELOCIDAD, CLAXON, la DEMO programada y `DEMO_ORIGINAL`. La DEMO programada se cancela mediante la API. Para la DEMO original autónoma (código 64), la interrupción física comprobada usa CLAXON (código 128). DETENER libera las salidas del ESP8266 y por sí solo no garantiza interrumpir esa secuencia. El enlace de dispositivo y la confirmación HTTP/WSS aportan evidencia de software.

## API y seguridad

- La **salud** se consulta en `GET /` y `GET /health/database`.
- La **identidad** comienza en `POST /plataforma/sesion` y habilita el perfil, el cambio de contraseña y el cierre. El catálogo de exhibición y la solicitud de invitado están en `/plataforma/catalogo` y `/plataforma/invitados/{vehicle}`.
- La **administración** se agrupa bajo `/plataforma/` e incluye dashboard, usuarios, modelos, unidades, asignación, titularidad, reservas, DEMOS de fábrica y auditoría.
- La **operación** se agrupa en `/plataforma/vehiculos/{vehicle}/...` para catálogo, estado, historial, movimientos, despacho y DEMOS. El servidor verifica el alcance por unidad y la capacidad de cada orden.
- Para **WSS**, el navegador solicita un ticket de un solo uso y se conecta a `/plataforma/ws/vehiculos/{vehicle}`. El ESP8266 usa `/plataforma/ws/dispositivos/{vehicle}` con credencial propia de la unidad.

Las cuentas usan contraseñas almacenadas con Argon2id. La API emite bearer con vigencia de 30 minutos para cuentas y 120 segundos para exhibición, almacena sus huellas y comprueba revocación, rol y pertenencia o reserva. El ticket WSS vence en 20 segundos y el servidor verifica el origen del navegador. Las claves `X-API-Key` pertenecen al modo histórico 4.2. En modo 4.3 se registran las rutas `/plataforma` y salud.

## Arquitectura y POO

`Settings` valida configuración. `MySQLDatabase` encapsula las conexiones y transacciones con PyMySQL y TLS. Las rutas FastAPI resuelven dependencias y delegan a servicios y repositorios; los modelos Pydantic verifican las entradas y respuestas. `Identity` representa la sesión autorizada. `DemoExecutionManager` coordina ejecución y cancelación. `PlatformEvents` gestiona las suscripciones y el despacho a dispositivos.

RDS mantiene vehículos, comandos, estado, historial y DEMOS históricas. Las tablas `iot_*` añaden inventario por modelo, capacidades, titularidad, sesiones, reservas, tickets, DEMOS 4.3 y auditoría. Una reasignación conserva el historial anterior y crea una nueva versión de titularidad para acotar los datos y las DEMOS privadas. Las DEMOS de fábrica se vinculan al modelo.

## Desarrollo y despliegue

Crea un entorno Python con las [dependencias de desarrollo](requirements-dev.txt) y usa `python -m pytest -q`. Para iniciar el laboratorio REST/WSS 4.3, prepara una instancia MySQL aislada, configura desarrollo con despacho inhibido y ejecuta `python -m scripts.local43`. La [guía técnica](docs/4.3/README.md) incluye los comandos y el alcance de las pruebas.

En producción, Caddy termina TLS y reenvía HTTP/WSS a FastAPI en `127.0.0.1:8000`. El servicio usa RDS mediante TLS con la CA correspondiente y configuración privada. El procedimiento de instalación, la configuración de la instancia y los respaldos de producción se gestionan por el canal operativo privado. Los [scripts de esquema](scripts/migrations/) son material de revisión técnica. Publicar el código en GitHub es independiente de la instalación en EC2, RDS y el ESP8266.

## Versiones y evidencia

La instalación inicial 4.3 se identificó en `a05534204c9bed3e64f102eefc9b16361060ff51`. La revisión final verificada por el propietario, incluida la edición de permisos de invitado, procede del hijo directo `63287b7b7d3e292812b7f78929bb7d7f8ae76883`. En esa revisión, `app/platform43/admin.py` actualiza el permiso de invitado conservando las capacidades existentes al editar sólo esos permisos.

El [sketch 4.3](firmware/Excavadora_IoT_AWS/Excavadora_IoT_AWS.ino) es la referencia de código fuente del candidato. `GruaRC` gestiona la actuación mediante el registro de desplazamiento, `GestorWiFi` la conectividad Wi-Fi y `ClienteAWS` el enlace WSS. El [firmware histórico de Unidad 3 y 4.2](https://github.com/yori7v7/vehiculo_iot_api_dev/tree/37e08f9a5f6183738705805270490e67c322424d/firmware/Excavadora_IoT_AWS) documenta el canal legado. La identidad binaria del firmware cargado queda sin verificar en este cierre.

La operación física y la interfaz en PC y teléfono vertical/horizontal fueron confirmadas por el propietario. Las suites locales prueban software con despacho inhibido o simulado. Este cierre documental carece de nuevas pruebas físicas, colaborativas con usuarios reales o de instalación en producción.

Las referencias de 4.1/4.2 conservan el contexto de la API key, Postman, GPIO y el prototipo de turnos con despacho simulado. [Portada histórica](https://github.com/yori7v7/vehiculo_iot_api_dev/blob/37e08f9a5f6183738705805270490e67c322424d/README.md) · [Turnos simulados históricos](docs/control_publico_temporal.md) · [Auditoría histórica HTTP](docs/auditoria_http.md) · [Procedimientos almacenados](docs/auditoria_sp.md).

**Contexto académico.** Actividad 4.3 de Implementación de Soluciones I, Ingeniería en Sistemas Computacionales. Diego Yorel Castelán Silva, Tecnológico Nacional de México — Instituto Tecnológico de Pachuca, 2026.
