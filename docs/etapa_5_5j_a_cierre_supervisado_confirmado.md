# 5.5-J-A — Verificación final del cierre supervisado (NodeMCU físico conectado)

**Fecha:** 12/11/2026, hora local del usuario. **Estado:** prueba de autorización bajo supervisión completada en laboratorio, con GPIO/74HC595 forzado a cero, batería desconectada y AWS apagado.

Secuencia previa: al detener el heartbeat administrativo, el estado pasó de `operador=guest, supervision=True, TTL=1` a `operador=bloqueado, supervision=False` y después `operador=admin, supervision=False`, sin reiniciar el dispositivo. Ver [evidencia de transición de estados](etapa_5_5j_a_supervision_timeout_nodemcu.md).

## Prueba complementaria tras vencimiento

```text
py .\cliente_55j.py estado
{"etapa":"5.5-J-A","simulado":true,"gpio_inhibido":true,
 "dispositivo_autenticado":true,"operador":"admin",
 "modo_turno":"administrador","turno_restante_s":0,
 "supervision_vigente":false,"supervision_ttl_s":0,"aws":false}

py .\cliente_55j.py mover --rol guest --codigo 9 --ms 250
[55-J] Rechazo HTTP 409: {"detail":"No tienes el turno exclusivo"}

py .\cliente_55j.py mover --rol admin --codigo 1 --ms 250
{"aceptada":true,"codigo":1,"simulado":true,
 "neutral_virtual":true,"motor":false}

py .\cliente_55j.py estado
{"dispositivo_autenticado":true,"operador":"admin","supervision_vigente":false}
```

**Conclusión:** el invitado perdió la autorización cuando caducó la supervisión y el servidor rechazó una orden posterior con HTTP 409; la cuenta de administración recuperó el control lógico y la sesión del NodeMCU permaneció autenticada. Esta evidencia completa la secuencia de negocio de **tiempo indefinido mientras existe supervisión**, revocación automática y exclusión de operadores a nivel de laboratorio.

**Límites:** no se adjuntó el log específico de acuse STOP de Arduino para el timeout; no se probó parada mecánica, latencia máxima de revocación ni seguridad ante caída física de motores. El programa `vigilar` no prueba presencia humana. No hay acceso invitado remoto por GitHub Pages ni despliegue AWS. El prototipo local 5.5-J no está integrado en el backend de producción.

**PR en borrador; no fusionar como control físico.**