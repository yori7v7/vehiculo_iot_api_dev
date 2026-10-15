# Auditoría de los 21 Stored Procedures — etapa 6

Fuente de verdad: `vehiculo_iot_rds.sql`, proporcionado por el usuario. No se
crean ni alteran tablas o procedimientos. Todos los repositorios ejecutan SP
con parámetros mediante `StoredProcedureExecutor`; las transacciones pertenecen
a los servicios. La integración de escrituras se comprueba con fakes; la
verificación real de esta etapa sólo utiliza lecturas.

En las rutas, `V` significa `/vehiculos/{id_vehiculo}` y `D` significa
`V/demos/{id_demo}`. Los números identifican exactamente los 21 procedimientos.

| # | Stored Procedure | Repository | Service y endpoint/flujo |
| --- | --- | --- | --- |
| 1 | `sp_crear_vehiculo` | `VehicleRepository.create` | `VehicleService.create` → POST `/vehiculos` |
| 2 | `sp_obtener_vehiculos` | `VehicleRepository.list` | `VehicleService.list` → GET `/vehiculos`; también diagnóstico `DatabaseHealthService` |
| 3 | `sp_obtener_vehiculo` | `VehicleRepository.get` | `VehicleService.get` → GET `V`; validación del padre en CRUD, estado, historial, movimiento y DEMO |
| 4 | `sp_actualizar_vehiculo` | `VehicleRepository.update` | `VehicleService.update` → PUT `V` |
| 5 | `sp_eliminar_vehiculo` | `VehicleRepository.delete` | `VehicleService.delete` → DELETE `V` |
| 6 | `sp_crear_comando` | `CommandRepository.create` | `CommandService.create` → POST `V/comandos` |
| 7 | `sp_obtener_comandos_vehiculo` | `CommandRepository.list_for_vehicle` | `CommandService.list_for_vehicle` → GET `V/comandos`; validación de pertenencia/activo en DEMO y movimiento |
| 8 | `sp_actualizar_comando` | `CommandRepository.update` | `CommandService.update` → PUT `V/comandos/{id_comando}` |
| 9 | `sp_eliminar_comando` | `CommandRepository.delete` | `CommandService.delete` → DELETE `V/comandos/{id_comando}` |
| 10 | `sp_actualizar_estado` | `StateRepository.update` | `MovementService.execute` → POST `V/movimientos`; `DemoExecutionService.apply_step` → cada paso de DEMO |
| 11 | `sp_obtener_estado` | `StateRepository.get` | `StateService.get` → GET `V/estado` e inicial WebSocket; conservación/relectura en movimientos individuales y pasos DEMO |
| 12 | `sp_registrar_historial` | `HistoryRepository.register` | **Sólo** `MovementService.execute`, en la transacción del movimiento individual. DEMO nunca lo llama |
| 13 | `sp_obtener_historial` | `HistoryRepository.list_for_vehicle` | `HistoryService.list_for_vehicle` → GET `V/historial`, hasta diez filas sin filtro de origen |
| 14 | `sp_crear_demo` | `DemoRepository.create` | `DemoService.create` → POST `V/demos` |
| 15 | `sp_obtener_demos` | `DemoRepository.list_for_vehicle` | `DemoService.list_for_vehicle` → GET `V/demos`; validación/relectura en CRUD y ejecución |
| 16 | `sp_actualizar_demo` | `DemoRepository.update` | `DemoService.update` → PUT `D` |
| 17 | `sp_eliminar_demo` | `DemoRepository.delete` | `DemoService.delete` → DELETE `D` |
| 18 | `sp_agregar_movimiento_demo` | `DemoMovementRepository.create` | `DemoMovementService.create` → POST `D/movimientos`; ID confirmado por diferencia de IDs y orden único en relectura, el SP no devuelve ID |
| 19 | `sp_obtener_movimientos_demo` | `DemoMovementRepository.list_for_demo` | `DemoMovementService.list_for_demo` → GET `D/movimientos`; `DemoExecutionService.prepare` obtiene dinámicamente N pasos |
| 20 | `sp_actualizar_movimiento_demo` | `DemoMovementRepository.update` | `DemoMovementService.update` → PUT `D/movimientos/{id_demo_movimiento}` |
| 21 | `sp_eliminar_movimiento_demo` | `DemoMovementRepository.delete` | `DemoMovementService.delete` → DELETE `D/movimientos/{id_demo_movimiento}` |

El POST `D/ejecutar` coordina `prepare` y una tarea del `DemoExecutionManager`.
No hay un SP de ejecución ni de cancelación: POST `D/cancelar` señala esa tarea,
interrumpe esperas y recoge su finalización. No se inventan endpoints para
procedimientos que ya forman parte de estos flujos.

## Evidencia reproducible

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Las pruebas anteriores ejercen los trece SP de vehículos, comandos, estado e
historial. Las pruebas de DEMO ejercen los ocho restantes mediante sus
repositorios, servicios y endpoints ASGI, con commit/rollback y validaciones.
Las pruebas de datos de ejecución rechazan cualquier SP no previsto e incluyen
una prohibición de `sp_registrar_historial`: verifican la secuencia obtenida del
SP, actualización por paso, conectividad actual y resultado posterior al commit.
Las pruebas del manager ejercen tiempos inyectados, eventos, cancelación,
concurrencia e interacción con WebSocket sin ejecutar una DEMO real.

Las lecturas reales de DEMO y movimientos no certifican escrituras reales:
esas pruebas funcionales quedan pendientes por instrucción del usuario.
