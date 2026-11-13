# Etapa 5.5-K-T — Reintentos idempotentes de solicitudes virtuales

**Estado:** contrato de pruebas y persistencia SQLite verificados. No está desplegado a AWS ni a `app/main.py` y no concede control físico. Se conserva la rama `feature/5-5a-dispositivo-protocolo-aislado`; `main` no se modificó.

## Problema resuelto

Si el navegador envía una solicitud y el servidor crea el ticket, pero se pierde el HTTP 201 antes de llegar al profesor, repetir un POST tradicional crearía otro ticket. K-T evita ese duplicado **cuando el navegador reutiliza el mismo par** de valores aleatorios: una clave de idempotencia y un secreto propuesto de sesión, ambos de 32 bytes codificados en Base64url sin relleno (43 caracteres).

- Cabeceras `Idempotency-Key` y `X-Browser-Proposal` de `POST /publico/vehiculos/1/solicitudes`, **solo en el contrato de pruebas KS**.
- **Primera creación:** HTTP **201**, respuesta con `request_id`, `browser_secret` igual a la propuesta, código de pantalla, `idempotent_replay=false`, `simulado=true`, `control_fisico=false`, `canDrive=false`.
- **Mismo par + misma identidad TCP verificada + ticket aún pendiente:** HTTP **200**, mismo `request_id`, misma sesión, `idempotent_replay=true`, sin crear otro ticket ni cobrar una segunda cuota.
- **Clave reutilizada con otro secreto, secreto reutilizado para otro ticket, cliente diferente, época vieja, ticket rechazado/aprobado/revocado/caducado:** rechazo fail-closed, normalmente HTTP **409**. No se revive una autorización virtual.
- **Datos incompletos, claves sin formato o idénticas:** HTTP **400**; si `kt_idempotency_required=True` y faltan ambas, HTTP **428**. La cuota por cliente/global sigue operando antes de crear nuevos tickets: HTTP **429**.
- El servidor guarda exclusivamente `key_digest` HMAC-SHA256 con salt privado, hash SHA-256 del secreto de sesión, identidad de cliente hash y ticket UUID. No escribe las claves originales en texto plano. La comprobación de época, búsqueda y creación ocurre **dentro del mismo BEGIN IMMEDIATE de K-Q**.
- Las entradas de deduplicación se eliminan junto con su ticket al purgar tickets cerrados. El reinicio de K-Q rota la época; un par antiguo no sirve para solicitar acceso después de reiniciar.

## Compatibilidad y limitaciones

K-S sigue siendo un servidor **solo para TestClient**. Su bandera `kt_idempotency_required` es **False por defecto** para conservar las pruebas anteriores de K-S: una petición sin cabeceras todavía puede crear tickets duplicados. Las nuevas pruebas K-T usan **True** para exigir el par. **No se debe publicar ni afirmar idempotencia universal con la opción legado.**

Las cabeceras de reintento deben ir sobre HTTPS con CORS estricto, sin cookies y sin registrar valores en los logs. La propuesta se mantiene en la memoria del navegador, no en query string, URL, localStorage o sessionStorage. **No enviar claves ni secretos a ChatGPT.**

K-T no sustituye infraestructura pública aislada, rate limiting real de borde, autoridad distribuida de sesiones ni la seguridad mecánica del vehículo. Una respuesta `autorizado` sigue siendo **virtual**; no habilita joystick, DEMO, STOP físico ni comandos para el ESP.

## Evidencia

GitHub Actions backend [43385380685](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43385380685), commit `5692a7c487586106bf3c137265e22e3d27c188b1`: **651 pruebas y 840 subpruebas aprobadas**.

`tests/test_kt_idempotency.py` verifica respuesta HTTP perdida, un solo ticket para seis solicitudes concurrentes, cuota que no se consume dos veces, falsificación de claves, reutilización de secretos, expiración, revocación, aprobación, nueva época tras reinicio y separación del contrato K-S legacy.

**Cliente web:** la rama experimental del frontend se está adecuando para generar/reutilizar ambos valores y no activar las dos banderas públicas. Su resultado debe citarse únicamente tras un CI de navegador aprobado; las pruebas Python no certifican al cliente JS.

## Próximo paso

Completar CI Node + Chrome del cliente K-T con un servidor mock que responda usando el secreto propuesto. Después integrar estos contratos solamente en un staging público aislado, sin ningún camino de despacho de movimientos. **AWS/RDS apagados, `main` sin tocar, sin conectar la batería.**
