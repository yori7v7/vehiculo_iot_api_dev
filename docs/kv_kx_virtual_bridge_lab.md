# K-V + K-X: autoridad compartida, SOLO laboratorio virtual

Estado: **PR en borrador; no fusionado, no desplegado, no habilita control físico**.

## Objetivo y aislamiento

`app/public_control/kv_kx_virtual_bridge_lab.py` crea una app ASGI **distinta** de `app.main` y del sidecar K-V de EC2. Reutiliza *sin modificar* los endpoints HTTPS, los controles de proxy/origen y las transacciones SQLite del `create_kv_virtual_app`. Instala en el **mismo proceso de laboratorio** el `KXDiagnosticWSSHub` ya implementado y el coordinador `VirtualOnlyAuthority`, que comparten un bloqueo de mutaciones/acciones.

El módulo no contiene ejecutable `uvicorn`, puerto, despliegue, GPIO ni cliente RDS. Su constructor requiere el valor exacto `KX_KV_VIRTUAL_BRIDGE_LAB=isolated_ci_only`, además de las precondiciones `APP_ENV=staging` y `ADMISSION_VIRTUAL_ONLY=enabled` del K-V existente y una clave HMAC de 32 bytes que **no debe ser real en CI**. Las rutas siguen exigiendo el perímetro K-V (origen, host, cabeceras del proxy, IP de origen pública y peer loopback). WSS rechaza peers que no sean loopback y el hub comprueba host, ausencia de Origin, handshake HMAC y STOP inicial firmado.

**No desplegar esta app en la instancia EC2 ni enrutarla desde Caddy.** La ruta `POST /__lab__/vehiculos/1/accion-virtual` no forma parte de la web pública y no está publicada. No proporciona mecanismos para activar motores.

## Contrato

- Entrada REST: `codigo` entero en `0,1,2,4,5,6,8,9,10`, `duracion_ms` entero `100..500` para movimiento o exactamente `0` para STOP. `X-Browser-Session` opaca y perímetro K-V verificados.
- El coordinador comprueba en SQLite permiso vigente *antes y después* del despacho WSS. Únicamente el hub autenticado con HMAC puede despachar. `KXDiagnosticWSSHub` espera el ACK firmado `recibida` y `neutral_reportado_no_fisico`, emite STOP firmado por cada movimiento y rechaza replays.
- Las mutaciones admin K-V (`/supervision`, `/aprobar`, `/rechazar`, `/revocar`) pasan por el **mismo** `asyncio.Lock` que las acciones. Al recibir una revocación correctamente autenticada, `interlock()` bloquea emisiones nuevas **antes** de adquirir el lock; después de la revocación durable se emite un STOP *virtual* y se cierra la sesión WSS para exigir autenticación fresca.
- Toda respuesta a la acción incluye `simulado=true`, `control_fisico=false`, `canDrive=false`, `motor=false`, `stop_fisico_confirmado=false`. La respuesta K-V a revocación conserva sus indicadores originales (sin afirmar STOP físico).
- Si caduca el permiso, se pierde el heartbeat, se pierde el transporte o SQLite no es verificable, la acción **falla cerrada**. El fencing K-Q al reiniciar invalida tickets previos.

## Pruebas de laboratorio y límites

La suite `tests/test_kv_kx_virtual_bridge_lab.py` comprueba precondiciones; clave HMAC de laboratorio; encabezados host/proxy; semántica estricta de comandos; rutas legacy ausentes; exclusividad y expiración de heartbeat; invalidación tras reinicio; WSS autenticado, STOP inicial, ACKs firmados; revocación y preempción de un despacho concurrente. El workflow `kv-kx-virtual-bridge-lab-ci.yml` además ejecuta regresiones existentes de K-X y K-V. Los resultados de CI deben inspeccionarse antes de usar el código.

**Limitaciones explícitas:** esta integración no conecta el firmware de movimiento real de ocho direcciones con la web. La lista de códigos está modelada, pero **sin movimiento mecánico**. Ningún ACK virtual prueba GPIO=0 medido, PC817 apagado, inmovilidad ni STOP físico efectivo. Una acción virtual en vuelo puede haber generado tráfico firmado antes de que llegue una revocación; el interlock evita nuevas órdenes y los tests comprueban que el resultado no se declare autorizado. Las salidas virtuales tienen caducidad corta, no equivalen a un freno físico.

## Bloqueos antes de habilitar carrito real

1. Diseñar y validar un **interlock físico independiente** y un watchdog en firmware que neutralice las salidas incluso si falla Wi-Fi, WSS, proceso, reloj o energía; medir la parada real.
2. Retirar todas las rutas alternativas que todavía puedan provocar movimiento: comandos Serial sin sesión, Swagger legacy, WSS legacy y cualquier puente físico fuera de la autoridad única.
3. Probar con ESP8266 real, batería desconectada y salida 74HC595/PC817 medida, el HMAC, anti-replay, caída/reconexión y exclusión de turnos antes de considerar actuación.
4. Diseñar una transacción de liberación física distinta de `canDrive=false`; ninguna autorización virtual de este PR la concede. Mantener modo físico denegado hasta auditoría y autorización humana de despliegue.

No cambiar `main`, Caddy, firmware, tareas Windows ni RDS durante esta etapa.
