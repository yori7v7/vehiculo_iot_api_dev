# 5.5-G — Evidencia de integración local WSS → USB → ESP8266

**Resultado confirmado el 12/11/2026 por ejecución en Windows con un
ESP8266 NodeMCU físico (firmware 5.5-E en diagnóstico).**

Entorno: servidor FastAPI en loopback, cliente puente Python autenticado por
WSS y ESP8266 conectado a través de COM4. AWS, RDS y los motores permanecieron
desconectados.

Salida observada:

```text
[55-G] Firmware 5.5-E en modo SIMULADO confirmado: OK
[55-G] Sesión WSS del puente autenticada: OK
[55-G] Orden 9 WSS -> USB -> ESP8266; acuses HMAC: OK (virtual)
[55-G] Orden 0 WSS -> USB -> ESP8266; acuses HMAC: OK (virtual)
[55-G] RESULTADO: WSS -> USB -> ESP8266 APROBADO; SIN MOTOR NI AWS
```

**Incidencia resuelta:** un primer intento fue rechazado por el firmware
con acuse de fase 3 (no fue registrado como éxito). Después de reiniciar
físicamente el NodeMCU, el ensayo pasó. Esto es consistente con la
protección antirreplay y la secuencia de prueba reiniciada, pero no demuestra
de forma independiente la única causa del rechazo.

**Alcance exacto:** FastAPI envió órdenes firmadas por WSS a un puente
Python, y este las retransmitió por USB al ESP8266; el microcontrolador
respondió con acuses autenticados. NO existió un WebSocket directo del
ESP8266 a FastAPI, ni credenciales de producción, ni movimiento físico,
ni validación de inmovilidad o relevo entre operadores.

**Próximo hito:** conexión WSS exclusiva del dispositivo con
autenticación fresca, firmware validando y acuse correlacionado,
sin transmitir todavía a PC817. Después unificar rutas administrativas
y público temporal con un único coordinador y ensayos físicos supervisados.

No fusionar ni desplegar este PR como control público real.
