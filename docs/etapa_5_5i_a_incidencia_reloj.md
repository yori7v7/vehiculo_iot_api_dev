# Incidencia 5.5-I-A — Orden de administrador rechazada por desfase reloj

**Fecha:** 12/11/2026. **Estado:** causa diagnosticada; parche del servidor preparado y validado en pruebas virtuales; pendiente repetición en el NodeMCU físico.

La primera ejecución en Windows confirmó que el ESP8266 autenticó correctamente y aceptó STOP inicial, pero rechazó el primer movimiento del administrador:

```text
[55-I] Dispositivo autenticado; STOP inicial virtual con acuses OK
[55-H] RECHAZO causa: codigoOK=1, secOK=1, epocaOK=1, relojOK=0, ttlOK=1, durOK=1, pendienteOK=1
[55-H] RECHAZO tiempos: delta_ms=-12 ttl_ms=1000
[55-H] RECHAZO datos: seq=2 esperada=2; gen=1 ant=1; epoca=2 ant=1; codigo=1 duracion=250
[55-I] Rechazo HTTP 503: {"detail":"Operacion fallida: sesion cerrada en modo seguro"}
```

El firmware 5.5-H permite hasta 100ms de desfase futuro **solo a STOP**; los movimientos exigen `issued <= now`. Windows emitió el movimiento ~12ms delante del reloj del ESP8266, por lo cual se rechazó según diseño. El servidor entró en modo seguro y los siguientes intentos recibieron HTTP 503.

**Corrección local propuesta para el laboratorio 5.5-I-A:**

- En `servidor_55i.py`, cambiar exclusivamente el instante de firma/emisión a `now = int(time.time() * 1000) - 150`.
- Mantener `expires_at_ms = now + 1000` (TTL del contrato inalterado, 1 segundo), HMAC, secuencia, época, duración y todos los rechazos del firmware.
- Esta retrodatación significa que, vista desde el servidor, la ventana útil es ~850ms desde la firma; no amplía el tiempo de movimiento y aún es superior a los 500ms de duración máxima.
- Se creó el parche PowerShell `parche_55i_reloj_150ms.ps1` con verificación de firmware seguro, respaldo automático y `py_compile`. El parche se entrega por chat para ejecutar localmente. **No cambiar ni volver a grabar el ESP8266.**
- El prototipo Python corregido y sus tests locales superaron **4 pruebas**, incluyendo órdenes verificadas con reloj del dispositivo 50ms atrasado, rechazo de HMAC corrupto y órdenes fuera de vigencia. Esto NO es validación de hardware de la corrección.

**Limitaciones:** no se han realizado nuevos movimientos físicos; salidas bloqueadas. La solución temporal requiere revisión de política de relojes y tolerancia antes de pasar a producción/AWS. Mantener el PR en borrador y los motores desconectados.
