# 5.5-I-A — Evidencia de turnos dinámicos con ESP8266 físico

**Fecha reportada:** 12/11/2026. **Resultado:** prueba local de laboratorio **APROBADA** con un NodeMCU ESP8266 real, servidor WSS Python y firmware 5.5-H en **diagnóstico seguro, salidas físicas inhibidas**.

## Evidencia de cliente Python (PowerShell)

```text
py cliente_55i.py estado
"dispositivo_autenticado": true, "operador": "admin", "gpio_inhibido": true

py cliente_55i.py mover --rol admin --codigo 1 --ms 250
"aceptada": true, "codigo": 1, "simulado": true, "neutral_virtual": true, "motor": false

py cliente_55i.py invitado --segundos 30
"turno": "guest", "segundos": 30, "parada_fisica_verificada": false

py cliente_55i.py mover --rol admin --codigo 2 --ms 250
[55-I] Rechazo HTTP 409: {"detail":"No tienes el turno exclusivo"}

py cliente_55i.py mover --rol guest --codigo 9 --ms 250
"aceptada": true, "codigo": 9, "simulado": true, "neutral_virtual": true, "motor": false

py cliente_55i.py detener
"detener": true, "neutral_virtual": true, "parada_fisica_verificada": false

py cliente_55i.py estado
"dispositivo_autenticado": true, "operador": "admin", "turno_restante_s": 0
```

## Evidencia correspondiente en Monitor Serie del NodeMCU

```text
[55-H] TLS independiente ESP -> PC: OK (CA verificada)
[55-H] TLS WSS conectado; esperando desafio.
[55-H] TLS + autenticacion mutua HMAC: OK
[55-H] DETENER 0 HMAC: OK, neutro virtual
[55-H] Orden 1 firmada: OK; GPIO inhibido, 250 ms virtuales.
[55-H] Neutral virtual firmado, no hay salida GPIO.
[55-H] DETENER 0 HMAC: OK, neutro virtual
[55-H] Orden 9 firmada: OK; GPIO inhibido, 250 ms virtuales.
[55-H] Neutral virtual firmado, no hay salida GPIO.
[55-H] DETENER 0 HMAC: OK, neutro virtual
```

## Incidencia y resolución

La primera prueba de la etapa fue interrumpida porque el ESP8266 estaba unos 12ms detrás del reloj del servidor; la orden de avance 1 firmada fue rechazada con `relojOK=0` y el servidor cerró WSS en modo seguro, devolviendo HTTP 503. La corrección de laboratorio *solo en el servidor* retrodató el instante de emisión 150ms y conservó HMAC, secuencia, época, TTL de 1000ms y validación estricta del cliente. Tras repetir la prueba, la secuencia completa tuvo éxito con hardware real.

El Monitor Serie también muestra **desconexiones y reconexiones WSS previas** a la secuencia exitosa. Esto requiere investigación y pruebas de reconexión/fail-safe antes de exponerlo a invitados remotos. El registro no permite atribuir cada reconexión a una causa específica.

## Alcance aprobado y restricciones

Se verificó que un servidor LAN autorizó dos identidades de control con exclusión, mandó órdenes cambiantes mediante WSS autenticado a un **NodeMCU físico**, verificó acuses virtuales firmados y recuperó el control administrativo después de STOP. El rechazo HTTP 409 durante el turno del invitado es el **comportamiento esperado**.

**No se probó movimiento real, parada mecánica, acceso desde otro equipo, acceso del profesor por un enlace público, GitHub Pages → AWS ni arbitraje contra las rutas administrativas antiguas.** La limitación `gpio_inhibido = true` está confirmada; mantener batería desconectada.

No fusionar ni desplegar como control físico de producción. La preempción real e inmediata de STOP, sesiones invitadas con autorización/caducidad seguras, watchdog y cierre ante pérdida de supervisor necesitan diseño y ensayos adicionales.
