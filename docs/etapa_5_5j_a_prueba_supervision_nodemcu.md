# 5.5-J-A — Evidencia de turno sin tiempo fijo bajo supervisión con ESP8266 real

**Fecha de prueba:** 12/11/2026 (hora local de México). **Resultado:** escenario manual de laboratorio con el ESP8266 real **APROBADO** para concesión supervisada, exclusión y revocación explícita. **La pérdida de supervisor por timeout aún NO fue ensayada en dispositivo físico.**

## Servidor LAN

```text
py .\servidor_55j.py
[55-J] SERVIDOR LOCAL DE TURNOS BAJO SUPERVISION — SIN MOTORES
[55-I] WSS PC: 192.168.1.82:8443; tokens y CA SOLO EN CARPETA PRIVADA
[55-J] Invitado indefinido solo con heartbeat admin: 5s / caducidad 15s.
[55-I] Dispositivo autenticado; STOP inicial virtual con acuses OK
```

## Supervisor en terminal independiente

```text
py .\cliente_55j.py vigilar
[55-J] Supervisando: se emitira heartbeat cada 5s.
[55-J] Latido supervisión aceptado; ventana 15.0s
[55-J] Latido supervisión aceptado; ventana 15.0s
...
```

## Control dinámico

```text
py .\cliente_55j.py invitado-supervisado
{"turno":"guest","segundos":null,"modo_turno":"supervisado",
 "requiere_heartbeat_admin_s":5.0,"timeout_supervisor_s":15.0,
 "simulado":true,"parada_fisica_verificada":false}

py .\cliente_55j.py estado
{"dispositivo_autenticado":true,"operador":"guest","modo_turno":"supervisado",
 "turno_restante_s":null,"supervision_vigente":true,"supervision_ttl_s":15}

py .\cliente_55j.py mover --rol admin --codigo 1 --ms 250
[55-J] Rechazo HTTP 409: {"detail":"No tienes el turno exclusivo"}

py .\cliente_55j.py mover --rol guest --codigo 9 --ms 250
{"aceptada":true,"codigo":9,"simulado":true,"neutral_virtual":true,"motor":false}

py .\cliente_55j.py detener
{"detener":true,"neutral_virtual":true,"parada_fisica_verificada":false}
```

## Interpretación y límites

La autenticación WSS, la concesión de un turno supervisado sin fecha de vencimiento fija, el bloqueo del otro operador, el despacho virtual de una orden dinámica y la revocación administrativa devolviendo neutro **sí se observaron con el dispositivo real conectado**. Los acuses y estados no demuestran parada mecánica.

**No se ha probado todavía el cierre por timeout de supervisor en el NodeMCU**; está cubierto por pruebas automatizadas locales de dispositivo virtual pero falta la ejecución física de laboratorio. El heartbeat de un proceso `vigilar` solo demuestra presencia de un programa, no supervisión humana real. El código sigue aislado en un ZIP local, no integra AWS ni la interfaz pública del profesor. El firmware fija GPIO/74HC595 en cero, batería desconectada.

Continuar pruebas locales, no publicar claves, tokens, Wi-Fi ni certificados privados; PR sigue en borrador.
