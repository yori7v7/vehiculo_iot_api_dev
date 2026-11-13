# Etapa 5.5-K-R — Persistencia privada de solicitudes y sesiones (virtual)

**Estado:** componente experimental IMPLEMENTADO y pruebas automatizadas. **NO conectado a FastAPI, K-G/K-C, Swagger, GitHub Pages, AWS, RDS ni actuadores.** Sin encender servidores públicos ni conectar batería del vehículo. Rama exclusiva: `feature/5-5a-dispositivo-protocolo-aislado`; `main` intacta.

## Antecedentes verificados

- K-L: el alumno ejecutó **16/16** pruebas HTTPS con ESP diagnosticado, y aprobó/revocó turnos virtuales desde una ruta local.
- K-O: el alumno informó **3/3** barreras HTTP tras desconectar y reconectar USB; estado local fue `200 -> 503 -> 503`. No demuestra STOP físico.
- K-Q: `KQRestartFence` ya crea un **contador durable de época** en SQLite privado, bloquea propietario único por archivo local y deja cualquier STOP no confirmado como `incierta` en recuperación. Es un componente aislado.

## Implementación K-R

`app/public_control/kr_ticket_ledger.py` agrega un registro `KRTicketLedger(fence, epoch, admin_proof, clock=...)` **sobre el MISMO archivo SQLite privado y exclusivo de K-Q**, en tablas nuevas `kr_meta` y `kr_ticket`. No altera la versión global del esquema de SQLite ni la base MySQL académica.

**Contrato interno, no expuesto a Internet:**

- `prepare()`: prepara tablas en una transacción y **revoca todos los tickets que sigan pendientes o aprobados de épocas previas** antes de abrir el registro. Un arranque nuevo de K-Q siempre rota `epoch`; reiniciar no restaura una autorización vieja.
- `request(client_identity)`: solo acepta la identidad de cliente que un perímetro de red de confianza ya verificó; **no aceptar `X-Forwarded-For` sin proxy de confianza**. Devuelve ID UUID, código visible de ocho caracteres y secreto efímero de 43 caracteres **una sola vez**; solo guarda SHA-256 del secreto en SQLite, no el valor original. La huella del cliente se calcula con HMAC-SHA256 usando sal aleatoria privada guardada en el archivo ACL protegido.
- `status(browser_secret)`: verifica el hash, **solo la época actual** y caducidad; devuelve `esperando_autorizacion`, `autorizado_virtual` o `revocado_o_caducado`. No devuelve tokens de movimiento.
- `snapshot(admin_proof)`: cola y turno virtual actual, sin secretos de navegador.
- `supervise(admin_proof)`, `approve_virtual(..., seconds)`, `reject`, `revoke`: requieren prueba administrativa; no permiten más de un turno virtual activo; la supervisión vence a los **15 s**, la aprobación virtual a los **120 s** como máximo. No existe ninguna función de movimiento ni de WSS.
- Solicitudes pendientes duran **120 s** por defecto y hay límites de **5 pendientes**, **3 por cliente en cinco minutos** y **40 globales en cinco minutos** (todos configurables dentro de límites). El servidor debe implementar además protección antiabuso real por red antes de permitir tráfico público.
- El registro conserva una marca `last_wall`. Si la hora de servidor retrocede o se vuelve inválida, **sella permanentemente la instancia y los tickets virtuales** en una transacción; nunca acepta el reloj corregido como razón para reabrir permisos.
- `app/public_control/kq_restart_fence.py` añade `transaction(epoch)`: comprobar autoridad y efectuar cambios **dentro del mismo BEGIN IMMEDIATE**; un `invalidate()` concurrente aborta una transacción antes del commit. No basta comprobar la época en una operación distinta.

**Persistencia de seguridad ≠ permiso de movimiento:** todas las respuestas de K-R indican `simulado=true`, `control_fisico=false`, `canDrive=false`. El hecho de que SQLite registre `autorizado_virtual` **no** autoriza un solo byte de movimiento. Ni HTTP ni WSS utilizan todavía K-R.

## Evidencia automatizada

`tests/test_kr_ticket_ledger.py` verifica:
1. Solo hashes en disco, sin secretos de navegador ni identidad de visitante en claro.
2. Aprobación virtual condicionada a supervisión vigente, un turno simultáneo, caducidad y revocación.
3. Rechazo explícito, tickets caducados, credenciales inválidas y secretos con caracteres Unicode.
4. Límites por cliente y globales con transacción SQLite, y persistencia del límite entre reinicios.
5. Reinicios sucesivos: las sesiones de la época vieja no reviven y sus rastros quedan revocados.
6. Reloj retrocedido: sello durable, denegación posterior aunque el reloj se corrija.
7. Doble propietario, desaparición de archivo, aprobaciones concurrentes y pérdida de autoridad K-Q.
8. Test de separación arquitectónica: ninguna ruta FastAPI ni K-G/K-C importa K-R y el módulo no despacha movimiento.

**CI confirmado antes del gate estático:** [43383196524](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43383196524): **636 tests y 840 subtests aprobados**. La ejecución posterior que incluye el test de separación arquitectónica se debe comprobar aparte.

## Lo que NO está aprobado

- No es admisión pública persistente operativa; no está conectado al frontend ni a las rutas K-I/K-K. No garantiza múltiples hosts ni escalamiento distribuido.
- El candado de `CoordinatorOwnership` aplica a un **solo host / archivo local**. Una laptop y EC2 separados requieren autoridad central con fencing distribuido y un transporte privado seguro. Jamás compartir SQLite por OneDrive/NFS.
- La identidad del visitante aún depende de un reverse proxy confiable; límites por IP y reputación deben implementarse y probarse en el borde público.
- El estado virtual no prueba STOP mecánico, watchdog autónomo, exclusividad física de joystick/Swagger/DEMO ni seguridad con batería.
- El contrato `autorizado_virtual` **no equivale** al modo de sesión física. No activar `canDrive` ni despliegue público basándose en este módulo.

## Siguiente incremento propuesto

**5.5-K-S — Contract tests y aislamiento del puente de admisión:** diseñar cómo el tráfico HTTPS del profesor llegará a un servicio público de **solo solicitudes**, con sesión persistente y límites. Mantener **separada y desconectada** la capacidad de enviar órdenes físicas. Validar token, reintentos e idempotencia contra servidor simulado antes de evaluar infraestructura AWS.

**AWS/RDS apagados.** PR backend #5 continúa como borrador. No modificar ramas `main` ni GitHub Pages.
