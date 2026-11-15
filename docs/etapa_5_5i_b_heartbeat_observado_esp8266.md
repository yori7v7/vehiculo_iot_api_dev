# 5.5-I-B — Heartbeat WSS: desconexión automática observada con ESP8266 real

**Fecha de prueba:** 12/11/2026 (hora local de Windows). **Entorno:** `servidor_55i.py` en LAN, `cliente_55i.py` en PowerShell, firmware de diagnóstico 5.5-H en NodeMCU ESP8266, batería del vehículo desconectada, AWS apagado.

## Resultado del monitoreo automático

Después de aplicar el parche local `parche_55i_b_heartbeat_wss.ps1`, que imprimió `Heartbeat WSS activado: ping 5s / timeout 5s`, el monitor de PowerShell consultó una vez por segundo el estado:

```text
18:48:33 | conectado=True
...
18:48:45 | conectado=True
18:48:46 | conectado=False
18:48:48 | conectado=False
...
18:49:04 | conectado=False
```

El usuario desconectó físicamente el USB del NodeMCU **durante el monitoreo**, pero el instante exacto de retirada del cable **no quedó registrado**. Por tanto, esta evidencia **no permite afirmar latencia de detección de 1 segundo ni medir el peor caso**. Sí demuestra que el servidor detectó la pérdida sin necesidad de emitir previamente una orden de movimiento.

## Rechazo de órdenes

En el cliente de administración:

```text
py .\cliente_55i.py estado
"dispositivo_autenticado": true

py .\cliente_55i.py mover --rol admin --codigo 1 --ms 250
[55-I] Rechazo HTTP 503: {"detail":"Operacion fallida: sesion cerrada en modo seguro"}

py .\cliente_55i.py estado
"dispositivo_autenticado": false

py .\cliente_55i.py mover --rol admin --codigo 1 --ms 250
[55-I] Rechazo HTTP 503: {"detail":"Dispositivo desconectado"}
```

El primer estado `true` era transitorio; las dos solicitudes de control fueron **rechazadas**, no se confirmó despacho.

## Alcance y pendientes

**Aprobado en laboratorio:** pérdida del transporte detectada por heartbeat y estado actualizado automáticamente, rechazos HTTP 503 sin dispositivo autenticado.

**No demostrado todavía:** latencia máxima de fallo/reconexión bajo distintas condiciones, STOP de prioridad eléctrica, desconexión real con motores actuando, monitoreo remoto ni turnos reales desde GitHub Pages. `gpio_inhibido=true`; acuses virtuales no prueban parada mecánica.

El parche local modifica el servidor 5.5-I; el cliente y el firmware del ESP8266 no cambian. No publicar claves privadas, certificados ni credenciales Wi-Fi. Continuar en rama de desarrollo y no fusionar como control físico.
