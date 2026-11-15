# Etapa 5.5-B — Exclusión administrativa e invitados (contrato aislado)

Este cambio crea `app/device_channel/dispatch_guard.py`, un guardián de
despacho para preparar la conexión entre el coordinador persistente de
turnos y el canal autenticado de dispositivo.

**IMPORTANTE:** No está conectado al WSS real, al coordinador en ejecución
ni a los motores. No desbloquea el control físico: `safe_for_physical_relay`
es siempre `False`. No sustituye las pruebas del firmware.

## Invariantes

- Solo un conductor (administrador o invitado) por sesión.
- Una nueva conexión invalida las generaciones anteriores.
- Solo ocho códigos direccionales, 100–500 ms, secuencia y época exactas.
- No puede haber dos movimientos pendientes simultáneos.
- DETENER invalida de inmediato el movimiento pendiente y tiene
  prioridad en la cola lógica; un reenvío del mismo STOP es idempotente.
- El ACK de STOP tiene que coincidir en sesión, operación, generación y época.
- Ni siquiera el ACK de neutral virtual libera al siguiente conductor:
  se exige comprobación adicional del supervisor para **laboratorio**.
- Si se pierde la sesión o vence una orden, se bloquea el movimiento.
- No hay credenciales, envíos de WSS, acceso a AWS/RDS ni GPIO.

## Validación

`python -m pytest -q tests/test_device_dispatch_guard.py`

**28 pruebas locales aprobadas**, incluidos 100 intentos simultáneos
de tomar un turno, bloqueo de administrator/invitado, STOP prioritario,
reconexión, pérdida de sesión y rechazo de límites inválidos.

## Pendiente para operar el vehículo

1. Arbitrar también todas las rutas heredadas del administrador y DEMO.
2. Unificar la barrera con `PublicControlCoordinator` y la base SQLite.
3. Contrato de comandos HMAC entre FastAPI y firmware con ACK de movimiento.
4. Fail-safe en ESP8266 ante pérdida de WSS, paradas y duraciones.
5. Criterio de parada física asistido o comprobable y pruebas supervisadas.
6. Habilitar modo real, desplegar en AWS y probar desde la URL pública.

La API pública de 5.2 continúa simulada y desactivada en producción.
No fusionar/desplegar como función real hasta cerrar los pendientes.
