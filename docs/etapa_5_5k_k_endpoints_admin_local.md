# Etapa 5.5-K-K — Rutas administrativas para el inspector oficial (LABORATORIO)

**Fecha:** 12/11/2026 (México). **Estado:** código implementado solo en `feature/5-5a-dispositivo-protocolo-aislado`, sin merge ni despliegue AWS. El ESP de laboratorio permanece con GPIO inhibidos. La URL de examen final seguirá siendo solo `https://yori7v7.github.io/control-iot-u4/`.

## Qué se implementó

Se registró `app/public_control/kk_admin_lab.py` en `app/main.py`, oculto de Swagger, con las cinco rutas **exactas** que espera `AdminApprovalClient` del frontend:

| Método | Ruta relativa a `/admin/vehiculos/1/control-publico/solicitudes` | Resultado |
|---|---|---|
| GET | `` | `{solicitudes,turno_activo,simulado:true,control_fisico:false}` |
| POST | `/supervision` | `{supervision:true,vigencia_s:15,simulado:true,control_fisico:false}` |
| POST | `/{request_id}/aprobar` | `{aprobada:true,simulado:true,control_fisico:false}` |
| POST | `/{request_id}/rechazar` | `{rechazada:true,simulado:true,control_fisico:false}` |
| POST | `/revocar` | `{revocado:true,simulado:true,control_fisico:false}` **solo tras STOP virtual confirmado** |

`request_id` es UUID; el modo de aprobación es `supervised` sin segundos o `timed` con un entero de 30–300 segundos (la interfaz usa 120). La clave administrativa histórica del backend se valida usando la dependencia **real** `app.security.api_key.require_api_key` y no se reenvía al navegador del invitado. Se rechaza el bearer de visitante. La autorización usa `KFBridge.controller`, que debe ser **el mismo objeto** de `app.state.kf_wss_controller`, sin instancias paralelas ni otra base de turnos.

**El servidor controla:** se exige `app_env=development`, `kg_lab_mode=True`, `kj_lab_enabled=True`, `legacy_handover.phase=exclusive`, `exclusive_device_control_enabled=True`, dispositivo conectado, `Host` esperado, HTTPS, `Origin=https://yori7v7.github.io`, cliente HTTP desde la **misma laptop** (loopback o IP local K-G configurada), sin query, cookies, token de navegador ni cabeceras de proxy no confiables. El CORS administrativo existente permite `X-API-Key` solo desde el origen Pages; el endpoint nuevo no incluye rutas de movimiento.

`app.main.create_app()` establece `kj_lab_enabled=False`, `kj_expected_host=None`. En `kg_bootstrap.py`, el modo local K-G define Host `192.168.1.82:8443` usando la IP que se lea en configuración (no hardcodear para otras redes) y habilita `kj_lab_enabled=True` **solo después** de autenticar ESP, recibir STOP HMAC, cerrar DEMO/REST legacy y completar el handover K-E. Al salir, cierra ese acceso de nuevo. Si el ESP se desconecta, K-K responde 503 por `controller.connected=False`.

### Pruebas y evidencia

1. `tests/test_kk_admin_lab.py` se subió a la rama, con pruebas HTTP del router, autenticación `require_api_key`, CORS, protección por IP/origen, validación estricta, ausencia en Swagger, conexión única, revocación y fallos. **Pendiente ejecutarlo en el árbol completo del repositorio** (`pytest`/CI o PC del alumno).
2. Se creó una **réplica aislada** del router con el mismo código funcional, FastAPI + `SingleLinkAdmissionLab` + `KFBridge` reales del laboratorio anterior y stubs de autenticación (sin la dependencia real del backend), y se ejecutaron **7 pruebas: 7 passed (0.37 s)**. Estas confirman la lógica de la ruta, pero **NO validan la integración completa ni el middleware CORS real**.
3. La etapa K-G anterior **sí** fue comprobada manualmente por el alumno con su NodeMCU físico, WSS HMAC y estados administrativos; K-K no ha sido probado todavía con ese hardware.

### Limitaciones esenciales

- **Este NO es un panel admin usable desde Internet**. Solo se habilita en el laboratorio K-G de **la laptop**; `guestAdmissionEnabled=false` y `adminApprovalEnabled=false` en el frontend, y K-I sigue cerrado. No se expone ningún nuevo permiso público del profesor.
- El navegador oficial en otro equipo aún no podrá realizar las peticiones K-K al puerto privado 8443. El servicio K-G local y el certificado LAN tampoco son un despliegue HTTPS apto para GitHub Pages remoto.
- Un latido de supervisión automático cada 5 segundos **no demuestra presencia humana**. Falta definir señales de presencia real y la política ante pestaña oculta, suspensión, pérdida de red o caída de administrador.
- No hay autoridad durable de turnos/épocas ante múltiples procesos y reinicios, protección contra spam con límites por IP, ni control remoto HTTPS de producción. **No se debe desplegar el K-G como AWS productivo**.
- STOP HMAC solo indica *neutro virtual*; faltan prioridad preemptiva real, watchdog de firmware, prueba física de neutralidad, límites eléctricos y validación supervisada antes de quitar `ETAPA54_DIAGNOSTICO_SEGURO=1`.
- Las escrituras históricas de Swagger/DEMO siguen aisladas del coordinador hasta futura unificación; nunca afirmar que están despachando por la autoridad única.

**No cambiar la rama `main`, no encender AWS/RDS, no configurar hotspot todavía y no conectar motores.** Registrar el PR como borrador.
