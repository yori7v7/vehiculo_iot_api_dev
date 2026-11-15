# 5.5-I-B — Pérdida y recuperación del enlace WSS en NodeMCU real

**Fecha de observación:** 12/11/2026. **Entorno:** servidor local `servidor_55i.py`, NodeMCU ESP8266 con firmware 5.5-H, salidas 74HC595 bloqueadas, sin batería ni AWS.

## Evidencia observada

**Primera consulta después de desconexión física del USB:**

```text
"dispositivo_autenticado": true
py cliente_55i.py mover --rol admin --codigo 1 --ms 250
[55-I] Rechazo HTTP 503: {"detail":"Operacion fallida: sesion cerrada en modo seguro"}
```

El servidor todavía mostraba `true` durante un intervalo no medido, pero al intentar enviar una orden cerró la sesión y **no confirmó movimiento**.

**Segunda consulta con el NodeMCU todavía desconectado:**

```text
"dispositivo_autenticado": false
[55-I] Rechazo HTTP 503: {"detail":"Dispositivo desconectado"}
```

**Reconexión tras conectar nuevamente el USB:**

```text
"dispositivo_autenticado": true
"operador": "admin"
py cliente_55i.py mover --rol admin --codigo 1 --ms 250
{"aceptada":true,"codigo":1,"simulado":true,"neutral_virtual":true,"motor":false}
"dispositivo_autenticado": true
"operador": "admin"
```

**Conclusión:** el rechazo fail-closed al perder el transporte y la recuperación de la sesión virtual fueron observados físicamente. No está medida ni demostrada la **latencia máxima** entre caída de cable y el cambio de `dispositivo_autenticado` a `false`.

## Siguiente endurecimiento propuesto

Añadir PING/PONG de transporte a `uvicorn.run` con `ws_ping_interval=5.0` y `ws_ping_timeout=5.0`, mediante parche local en PowerShell; validar la compatibilidad con la librería WebSocketsClient del ESP8266 y medir el tiempo real hasta detección. Este ajuste puede acotar la detección de sockets muertos, pero **no da STOP mecánico inmediato, no prueba desconexión eléctrica ni reemplaza un watchdog local de actuadores**.

Se verificó el patrón de cambio de configuración del servidor, se comprobó sintaxis Python y **4 pruebas virtuales previas de contratos dinámicos**. La ejecución del parche y su comportamiento con dispositivo físico permanecen pendientes en esta evidencia.

**Restricciones:** entorno local-only, CA y tokens privados, no AWS/RDS, PC817 neutro forzado, batería desconectada. No fusionar ni desplegar como control público físico.
