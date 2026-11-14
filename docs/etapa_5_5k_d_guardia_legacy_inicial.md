# 5.5-K-D — Auditoría inicial y barrera de rutas legacy

**Fecha:** 12/11/2026, hora México. **Estado:** guardia en rama experimental; **apagada por defecto** para no modificar el comportamiento actual de AWS/Swagger. Se ejecutaron **5 pruebas aisladas de la dependencia FastAPI**, todas aprobadas. **NO validado aún con app completa/RDS/AWS; no significa que los endpoints estén conectados a K-C.**

## Evidencia K-C que desencadena la etapa

El usuario ejecutó el ZIP K-C con ESP8266 real y obtuvo éxito en solicitud, aprobación de visita, exclusión del administrador con HTTP 409, orden virtual diagonal 9, DETENER con neutro virtual, revocación y retorno administrativo. [Prueba manual y limitaciones](etapa_5_5k_c_prueba_manual_esp8266_aprobada.md).

El estado terminal `supervision_vigente=false` es **esperado cuando operador=admin**, dado que el cálculo heredado en `servidor_55j.py` es `running and supervised`. No afirma ausencia de pulsos del proceso administrador: para la versión final deben exponerse indicadores separados `heartbeat_admin_reciente` y `turno_invitado_supervisado`.

## Auditoría de rutas y fuentes de movimiento

Se revisaron en rama experimental:

- `app/routers/movement.py`: `POST /vehiculos/{id}/movimientos` (persistencia, broadcast WebSocket); ya usaba `Depends(require_legacy_dispatch)`.
- `app/routers/demo_execution.py`: `POST /vehiculos/{id}/demos/{id_demo}/ejecutar` y `/cancelar` (secuencia de base de datos y eventos WSS); también usan la dependencia.
- `app/websocket/router.py`: `/ws/vehiculos/{id}` en el backend existente solo maneja **suscripciones de lectura**; no es el WSS firmado de K-C.
- `app/execution/manager.py`: tareas de DEMO asíncronas con vida propia; una DEMO iniciada **antes** de activar el bloqueo podría seguir ejecutándose: la nueva dependencia por sí sola NO la cancela. Hay que detener y recoger la tarea antes de habilitar coordinador exclusivo.
- `app/public_control/http.py`: simulado, separado del WSS del ESP y con control loopback; no usar sus rutas como entrada pública física.
- `app/main.py`: monta ambas familias de routers y el WSS de laboratorio separado, sin integrar K-C todavía.

## Cambio realizado (rama experimental únicamente)

Se extendió `app/public_control/legacy_guard.py` para bloquear solicitudes a los endpoints ya protegidos cuando

```python
application.state.exclusive_device_control_enabled = True
```

o cuando ya está activo `public_control_simulation`. El archivo `app/main.py` define explícitamente `exclusive_device_control_enabled = False` al crear la app.

Esto conserva los endpoints heredados en modo normal para la actividad ya entregada. Una vez que exista el coordinador único **dentro de ese mismo proceso**, la transición a `True` tendrá que ser transaccional y esperar antes a que no queden DEMO/operaciones en vuelo.

**IMPORTANTE:** cambiar el atributo desde un script, REST o Swagger **no se ha implementado**; no hay endpoint público para ello. No activar manualmente mientras la autoridad única esté aislada en otro proceso; la protección no se sincronizaría entre instancias ni los workers de Uvicorn.

## Pruebas

`tests/test_exclusive_legacy_guard_kd.py` añade 5 escenarios con una aplicación FastAPI mínima y la dependencia real:

- Ruta heredada sigue operando con flag por defecto desactivado.
- Las tres rutas de movimiento/ejecución/cancelación probadas se rechazan HTTP 503 si el flag exclusivo es verdadero, sin ejecutar handlers.
- El modo simulado antiguo sigue imponiendo bloqueo.
- Una ruta GET de lectura de estado permanece disponible.
- Sin flag explícito se conserva el comportamiento legacy (esto significa que la futura activación no puede depender de una variable opcional que se pierda al reiniciar).

**Resultado en laboratorio Python:** `5 passed in 0.26s`. Quedan pendientes pruebas contra routers completos, regresión de suite y concurrencia con DEMO activa; NO se probó producción.

## Brechas antes de AWS y control físico

1. Integrar K-C dentro de la app productiva y usar un estado propietario **persistente/consistente** con una sola autoridad; no habilitar múltiples Uvicorn workers con estado de turnos en memoria.
2. Diseñar fase de transición: cerrar nuevas operaciones legacy, cancelar/drenar DEMO activa, confirmar STOP firmado con dispositivo o fail-closed, y recién después permitir invitaciones.
3. Unificar todos los despachos (administrador de Swagger, frontal, DEMO e invitado) por la misma barrera de permisos/época. Bloquear POST legacy es un parche de cierre, **no sustituye el coordinador**.
4. DETENER debe tener una prioridad real sobre cualquier movimiento en vuelo; el K-C actual encola STOP detrás del `asyncio.Lock`, y su ACK virtual **no verifica parada mecánica**.
5. Adaptar frontend original de GitHub Pages (una URL, sin texto adicional al docente) y validar desde otro dispositivo antes de pasar al hotspot; dejar red del examen configurada y ensayada con anticipación.
6. El firmware ESP8266 con `ETAPA54_DIAGNOSTICO_SEGURO 1` continúa inhibiendo motores; batería desconectada durante todas las etapas de software.

**PR sigue en borrador, `main` sin modificaciones; AWS/RDS apagados.**
