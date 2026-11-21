# Inventario local de la API

Inventario HTTP por modo de ejecución. La restauración 4.2 es un laboratorio histórico. El contrato vigente se documenta en Swagger 4.3. Los WebSockets se describen al final.

## API de restauración 4.2 (histórica)

| Método | Ruta | Función | Credencial declarada | Entrada | Respuesta |
| --- | --- | --- | --- | --- | --- |
| GET | / | Comprobar que FastAPI está funcionando | Pública | — | 200 HealthResponse |
| GET | /health/database | Comprobar conexión Python → RDS y lectura de un SP | Pública | — | 200 DatabaseHealthResponse |
| GET | /vehiculos | Listar vehículos | Pública | — | 200 lista[VehicleResponse] |
| POST | /vehiculos | Crear vehículo | LocalApiKey | VehicleCreate | 201 VehicleResponse |
| GET | /vehiculos/{id_vehiculo} | Consultar vehículo | Pública | — | 200 VehicleResponse |
| PUT | /vehiculos/{id_vehiculo} | Reemplazar datos de un vehículo | LocalApiKey | VehicleUpdate | 200 VehicleResponse |
| DELETE | /vehiculos/{id_vehiculo} | Eliminar vehículo | LocalApiKey | — | 204 ver OpenAPI |
| POST | /vehiculos/{id_vehiculo}/comandos | Crear un comando del vehículo | LocalApiKey | CommandCreate | 201 CommandResponse |
| GET | /vehiculos/{id_vehiculo}/comandos | Listar los comandos de un vehículo | Pública | — | 200 lista[CommandResponse] |
| PUT | /vehiculos/{id_vehiculo}/comandos/{id_comando} | Actualizar un comando del vehículo | LocalApiKey | CommandUpdate | 200 CommandResponse |
| DELETE | /vehiculos/{id_vehiculo}/comandos/{id_comando} | Eliminar un comando del vehículo | LocalApiKey | — | 204 ver OpenAPI |
| GET | /vehiculos/{id_vehiculo}/estado | Consultar estado persistido del vehículo | Pública | — | 200 StateResponse o null |
| GET | /vehiculos/{id_vehiculo}/historial | Consultar hasta diez registros recientes del historial | Pública | — | 200 lista[HistoryResponse] |
| POST | /vehiculos/{id_vehiculo}/movimientos | Registrar un movimiento individual del vehículo | LocalApiKey | MovementRequest | 200 MovementResponse |
| POST | /vehiculos/{id_vehiculo}/demos | Crear una DEMO del vehículo | LocalApiKey | DemoCreate | 201 DemoResponse |
| GET | /vehiculos/{id_vehiculo}/demos | Listar las DEMO del vehículo | Pública | — | 200 lista[DemoResponse] |
| PUT | /vehiculos/{id_vehiculo}/demos/{id_demo} | Actualizar una DEMO del vehículo | LocalApiKey | DemoUpdate | 200 DemoResponse |
| DELETE | /vehiculos/{id_vehiculo}/demos/{id_demo} | Eliminar una DEMO del vehículo | LocalApiKey | — | 204 ver OpenAPI |
| POST | /vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos | Agregar un movimiento a la DEMO | LocalApiKey | DemoMovementCreate | 201 DemoMovementResponse |
| GET | /vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos | Listar los movimientos de la DEMO | Pública | — | 200 lista[DemoMovementResponse] |
| PUT | /vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos/{id_demo_movimiento} | Actualizar un movimiento de la DEMO | LocalApiKey | DemoMovementUpdate | 200 DemoMovementResponse |
| DELETE | /vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos/{id_demo_movimiento} | Eliminar un movimiento de la DEMO | LocalApiKey | — | 204 ver OpenAPI |
| POST | /vehiculos/{id_vehiculo}/demos/{id_demo}/ejecutar | Iniciar DEMO en segundo plano | LocalApiKey | — | 202 DemoExecutionResponse |
| POST | /vehiculos/{id_vehiculo}/demos/{id_demo}/cancelar | Cancelar la DEMO activa del vehículo | LocalApiKey | — | 200 DemoExecutionResponse |

## API de plataforma 4.3

| Método | Ruta | Función | Credencial declarada | Entrada | Respuesta |
| --- | --- | --- | --- | --- | --- |
| GET | / | Comprobar que FastAPI está funcionando | Pública | — | 200 HealthResponse |
| GET | /health/database | Comprobar conexión Python → RDS y lectura de un SP | Pública | — | 200 DatabaseHealthResponse |
| POST | /plataforma/sesion | Iniciar sesión durante 30 minutos | Pública | Login | 200 ver OpenAPI |
| DELETE | /plataforma/sesion | Logout | HTTPBearer | — | 204 ver OpenAPI |
| GET | /plataforma/perfil | Profile | HTTPBearer | — | 200 ver OpenAPI |
| PUT | /plataforma/perfil/password | Password | HTTPBearer | ChangePassword | 204 ver OpenAPI |
| GET | /plataforma/dashboard | Dashboard | HTTPBearer | — | 200 ver OpenAPI |
| GET | /plataforma/usuarios | Clients | HTTPBearer | — | 200 ver OpenAPI |
| POST | /plataforma/usuarios | Register Client | HTTPBearer | Client | 201 ver OpenAPI |
| PUT | /plataforma/usuarios/{client}/acceso | Client Access | HTTPBearer | Access | 204 ver OpenAPI |
| GET | /plataforma/modelos | Models | HTTPBearer | — | 200 ver OpenAPI |
| POST | /plataforma/modelos | Add Model | HTTPBearer | Model | 201 ver OpenAPI |
| PUT | /plataforma/modelos/{model} | Update Model | HTTPBearer | Model | 200 ver OpenAPI |
| GET | /plataforma/unidades | Units | HTTPBearer | — | 200 ver OpenAPI |
| POST | /plataforma/unidades | Add Unit | HTTPBearer | NewUnit | 201 ver OpenAPI |
| PUT | /plataforma/unidades/{vehicle} | Update Unit | HTTPBearer | Unit | 200 ver OpenAPI |
| PUT | /plataforma/unidades/{vehicle}/asignacion | Transfer | HTTPBearer | Transfer | 200 ver OpenAPI |
| GET | /plataforma/unidades/{vehicle}/titularidad | Ownership | HTTPBearer | — | 200 ver OpenAPI |
| GET | /plataforma/auditoria | Audit Log | HTTPBearer | — | 200 ver OpenAPI |
| GET | /plataforma/modelos/{model}/demos | Factory List | HTTPBearer | — | 200 ver OpenAPI |
| POST | /plataforma/modelos/{model}/demos | Factory New | HTTPBearer | Demo | 201 ver OpenAPI |
| PUT | /plataforma/modelos/{model}/demos/{demo} | Factory Edit | HTTPBearer | Demo | 200 ver OpenAPI |
| GET | /plataforma/vehiculos/{vehicle}/demos/privadas | Private List | HTTPBearer | — | 200 ver OpenAPI |
| POST | /plataforma/vehiculos/{vehicle}/demos/privadas | Private New | HTTPBearer | Demo | 201 ver OpenAPI |
| PUT | /plataforma/vehiculos/{vehicle}/demos/privadas/{demo} | Private Edit | HTTPBearer | Demo | 200 ver OpenAPI |
| GET | /plataforma/catalogo | Catalog | Pública | — | 200 ver OpenAPI |
| POST | /plataforma/invitados/{vehicle} | Guest | Pública | — | 201 ver OpenAPI |
| GET | /plataforma/reservas | Reservations | HTTPBearer | — | 200 ver OpenAPI |
| DELETE | /plataforma/reservas/{vehicle} | Cancel Reservation | HTTPBearer | — | 204 ver OpenAPI |
| GET | /plataforma/vehiculos | My Vehicles | HTTPBearer | — | 200 ver OpenAPI |
| GET | /plataforma/vehiculos/{vehicle} | Get Vehicle | HTTPBearer | — | 200 VehicleResponse |
| GET | /plataforma/vehiculos/{vehicle}/comandos | Get Commands | HTTPBearer | — | 200 lista[CommandResponse] |
| GET | /plataforma/vehiculos/{vehicle}/despacho | Consultar la disponibilidad del enlace de dispositivo autorizado | HTTPBearer | — | 200 ver OpenAPI |
| GET | /plataforma/vehiculos/{vehicle}/estado | Get State | HTTPBearer | — | 200 StateResponse o null |
| GET | /plataforma/vehiculos/{vehicle}/historial | History | HTTPBearer | — | 200 lista[HistoryResponse] |
| POST | /plataforma/vehiculos/{vehicle}/movimientos | Move | HTTPBearer | MovementRequest | 200 MovementResponse |
| GET | /plataforma/vehiculos/{vehicle}/demos | Available Demos | HTTPBearer | — | 200 lista[DemoResponse] |
| GET | /plataforma/vehiculos/{vehicle}/demos/{demo}/movimientos | Demo Steps | HTTPBearer | — | 200 lista[DemoMovementResponse] |
| POST | /plataforma/vehiculos/{vehicle}/demos/{demo}/ejecutar | Start Demo | HTTPBearer | — | 202 DemoExecutionResponse |
| POST | /plataforma/vehiculos/{vehicle}/demos/{demo}/cancelar | Cancel Demo | HTTPBearer | — | 200 DemoExecutionResponse |
| POST | /plataforma/vehiculos/{vehicle}/ticket | New Ticket | HTTPBearer | — | 201 ver OpenAPI |

## Canales WebSocket 4.3

- Navegador en `/plataforma/ws/vehiculos/{vehicle}` con ticket de un solo uso y validación de origen.
- Dispositivo en `/plataforma/ws/dispositivos/{vehicle}` con la credencial de su unidad.
