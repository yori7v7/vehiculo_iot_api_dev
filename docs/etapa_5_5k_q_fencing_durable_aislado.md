# Etapa 5.5-K-Q — Fencing durable de épocas (aislado, sin control físico)

**Estado:** implementación experimental con pruebas automatizadas; **NO está conectado** a K-G, K-C, AWS, RDS, Swagger, DEMO o rutas HTTP. No hay nuevo permiso remoto de movimiento. Ambas ramas `main` permanecen sin cambios.

## Motivo

K-O validó en la laptop (13/11/2026) **3/3 barreras HTTP**: 17 GET estables durante 12 s con ESP conectado; HTTP 503 tras pérdida USB; HTTP 503 persistente después de reconectar. Sin embargo, el modelo de tickets K-C en memoria todavía no puede garantizar continuidad y exclusividad si el servidor se reinicia o hay procesos simultáneos. Un éxito HTTP virtual no equivale a parada física.

Existe previamente un almacén local privado `PublicControlRepository` con SQLite transaccional, validación de identidad del archivo, migración y `CoordinatorOwnership` por host. K-Q reutiliza ese código, **en un archivo de prueba dedicado y separado de todas las otras bases**.

## Artefacto K-Q

`app/public_control/kq_restart_fence.py` implementa `KQRestartFence(path)`. Su método `start()`:
1. Adquiere el candado exclusivo por proceso/host mediante `CoordinatorOwnership`; una segunda instancia sobre el mismo archivo no puede arrancar.
2. Inicializa el esquema privado de SQLite y abre una transacción con `BEGIN IMMEDIATE`.
3. Incrementa durablemente `epoch`, `generation`, `revision` del vehículo 1; si hay restos de sesiones, los marca `active=0`, cierra las ventanas y deja `blocked_reason='kq_virtual_sin_traspaso_fisico'`.
4. Una operación de movimiento aceptada/despachada antigua pasa a **incierta**, al igual que un STOP/revocación pendiente. Nunca inventa una confirmación STOP.
5. `assert_current(epoch)` rechaza cualquier época previa o inválida, y `invalidate()` rota la época y bloquea para siempre la instancia actual, exigiendo arranque nuevo para otra época.

**NO** hay métodos que concedan acceso público, muevan el vehículo, entreguen credenciales administrativas, contacten ESP por WSS ni habiliten `canDrive`. Esto es una pieza de persistencia y fencing, no un componente listo para publicar.

## Validación

Archivo `tests/test_kq_restart_fence.py`:
- Época inicial bloqueada y tipos inválidos.
- Reinicios sucesivos invalidan generaciones antiguas.
- Dos instancias simultáneas no adquieren la misma autoridad ni alteran accidentalmente la época.
- La invalidación es irreversible para la misma instancia.
- Recuperación transaccional de ventanas/turnos antiguos y movimiento/STOP inciertos.
- Pérdida del archivo de coordinación causa rechazo; nunca se crea un repositorio nuevo silenciosamente.
- Dos intentos concurrentes de invalidar no dejan dos propietarios con autoridad.

**CI aprobada:** [GitHub Actions 43382108223](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43382108223), commit `cb3f1562729a674b708b2dd4669550df99524d53`: **625 pruebas y 840 subpruebas aprobadas**.

## Pendientes críticos para uso remoto / AWS

- **K-Q es un componente aislado**. Se requiere decidir y probar cómo conectar su época al **único coordinador WSS de todas las vías de movimiento**, incluyendo Swagger, DEMO, joystick y STOP. No sería seguro dar HTTP 200 de aprobación sin un traspaso físico certificado.
- El candado local solo funciona en **un mismo host**; para múltiples instancias o EC2 + laptop se necesita almacenamiento compartido de sesiones y elección/fencing atómicos distribuidos. No trasladar este archivo SQLite entre hosts vía carpeta sincronizada.
- La cola de tickets K-C sigue en RAM. Necesita estado durable por solicitud, token opaco con hash, TTL, límite antiabuso y recuperación fail-closed; no reutilizar sesiones virtuales antiguas como órdenes físicas.
- La expiración lógica/HTTP 503 **no prueba parada mecánica**. Es obligatorio comprobar watchdog autónomo, interlock y neutralidad física antes de habilitar motores remotamente.
- Falta probar operaciones concurridas ante reinicio abrupto, rollback de reloj, suplantación de proxy y pérdida de supervisor desde la API pública.
- Las credenciales privadas siguen fuera del repositorio. No subir `.env`, certificados privados, secretos HMAC, claves API ni logs que los incluyan.

**Estado de AWS/RDS:** APAGADOS. El próximo incremento debe construir y auditar el contrato de persistencia de tickets (sin conectarlo aún a los actuadores), y diseñar un despliegue público de admisión separado de la autoridad de motores.
