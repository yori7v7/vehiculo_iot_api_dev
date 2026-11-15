# Etapa 5.5-K-E — Barrera transaccional de transferencia para escrituras legacy

**Fecha:** 12/11/2026 (México). **Estado:** cambio realizado **únicamente en rama experimental**. Se ejecutaron **16 pruebas automatizadas en un entorno FastAPI aislado**, todas correctas: 8 para la nueva barrera, 5 de compatibilidad K-D y 3 del adaptador gestor DEMO. **NO** se probó la suite completa del repositorio productivo ni AWS; **NO** se habilitó movimiento físico ni se fusionó el PR.

## Por qué es necesario

Antes de esta etapa, `require_legacy_dispatch` comprobaba únicamente banderas al entrar a cada petición. Si una escritura antigua ya había entrado, modificar una bandera no garantizaba que su transacción MySQL hubiese terminado. Además, una DEMO puede seguir ejecutándose después de que su POST haya respondido.

## Código nuevo

- `app/public_control/legacy_handover.py`: `LegacyHandoverGate`, con fases `legacy` → `draining` → `exclusive` o `blocked`, `asyncio.Condition`, contador de solicitudes protegidas y `legacy_request()` de ciclo completo.
- `app/public_control/legacy_guard.py`: ahora es una dependencia con `yield` de FastAPI y mantiene contabilizadas las operaciones mientras sus handlers corren. Sigue respetando `public_control_simulation` y la bandera conservadora `exclusive_device_control_enabled` introducida en K-D.
- `app/main.py`: instancia `application.state.legacy_handover = LegacyHandoverGate()`, que inicia en `legacy`, sin alterar la disponibilidad de comandos ya existentes.
- `app/public_control/exclusive_transition_lab.py`: adaptador interno **NO HTTP** que llama a `LegacyHandoverGate.prepare_exclusive`, suministrando `application.state.demo_execution_manager.close_all` y exigiendo un callback futuro confiable `signed_stop_ack`.
- `tests/test_legacy_handover_ke.py` y `tests/test_exclusive_transition_lab.py`: escenarios de transición, concurrencia, fallos, timeout, cancelación, regresión K-D y orden de operaciones.

## Secuencia exigida para una futura transferencia autorizada

1. Cambiar atómicamente la fase a `draining`. Todas las **nuevas** escrituras legacy protegidas comienzan a recibir HTTP 503.
2. Esperar a que finalicen las peticiones anteriores ya admitidas; las rutas de lectura no se bloquean.
3. Ejecutar `DemoExecutionManager.close_all()` para cancelar y recoger DEMO que sobrevivieron al POST.
4. Pedir y verificar **desde el transporte WSS seguro** un STOP firmado y su acuse autenticado. El callback no existe aún conectado al servidor AWS.
5. Solo tras el éxito de todos los pasos, marcar la fase `exclusive`. Si ocurre excepción, timeout o cancelación, la fase pasa a `blocked`, y se rechazan nuevas escrituras legacy.

**La fase `exclusive` NO autoriza motores por sí misma**, no equivale a parada mecánica y no concede permisos a visitantes. El callback de pruebas que devuelve `True` únicamente demuestra orden de programación; no constituye acuse firmado del ESP8266. Nunca aceptar una confirmación de STOP como parámetro suministrado por el navegador.

## Evidencia automatizada

`python -m pytest -q tests` en sandbox aislado que incluye el código del cambio: **16 passed in 0.34s**. Se probaron las dependencias con rutas ASGI mínimas y un gestor DEMO falso; no se ejecutó la suite del repositorio completo en ese entorno.

Las pruebas cubren: cierre de rutas de movimiento/inicio/cancelación de DEMO, lecturas permitidas, solicitud en vuelo que debe terminar antes de cerrar DEMO, fallo de cancelación, fallo de STOP, STOP no confirmado, timeout, cancelación asíncrona, falta de gestor DEMO y regresión a bandera antigua.

## Límites críticos que aún impiden desplegar

- **No integrado con el servidor WSS K-C en el backend productivo.** K-C sigue como proceso local separado de la app FastAPI actual.
- **No existe ruta ni programa de activación de `prepare_exclusive_for_lab` en producción.** Se dejó sin activar deliberadamente.
- La fase y el contador están en la memoria de **un único proceso**. **No protegen múltiples workers de Uvicorn, múltiples instancias AWS ni reinicios.** Un reinicio vuelve a `legacy`: no es seguro usar este estado efímero para arbitrar motores.
- En producción se necesita autoridad de turno persistente, cierre seguro tras reinicio, fencing epoch monotónico y programa de transición bajo propietario único (sistema estable de exclusión multiworker).
- No hay prioridad preemptiva física de STOP: el coordinador K-C aún serializa órdenes con retardo posible y el acuse virtual no acredita parada mecánica.
- Hay que probar la integración completa de RDS, WSS, Swagger, DEMO y el frontend bajo concurrencia controlada antes de habilitar motores.
- El ESP8266 seguirá en Wi-Fi de casa por ahora; configurar laptop y ESP con hotspot del teléfono **al cierre del software y antes del examen**, con prueba integral ensayada. El enlace oficial del docente debe ser solamente `https://yori7v7.github.io/control-iot-u4/`, con solicitud automática y autorización manual por el dueño.

**No cambiar la rama `main`, no desplegar K-E a AWS ni activar firmware físico. PRs en borrador.**
