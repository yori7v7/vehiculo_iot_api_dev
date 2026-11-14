# 5.5-K-J — Contrato administrativo requerido por la página oficial (PENDIENTE)

**Fecha:** 12/11/2026. **Estado:** especificación; ninguna de estas rutas nuevas está implementada aquí ni desplegada en AWS. El frontend de rama `feature/5-5k-portal-unico-invitado` ya implementó un panel desactivado por defecto dentro del inspector existente y **13 pruebas JavaScript de lógica aprobadas** sobre sus fuentes; véase [documentación de K-J](https://github.com/yori7v7/control-iot-u4/blob/feature/5-5k-portal-unico-invitado/assets/docs/etapa_55kj_panel_admin_inactivo.md).

## Rutas previstas (HTTPS, solo administrador)

Todas bajo `/admin/vehiculos/{id_vehiculo}/control-publico/solicitudes`, con X-API-Key de administrador solo en el navegador de su laptop, y el mismo controlador de sesiones que gestiona el WSS del ESP8266:

- `GET /` → `{solicitudes:[{request_id,display_code,vence_en_seg}],turno_activo,simulado:true,control_fisico:false}`
- `POST /supervision` → confirma heartbeat 15s exclusivamente en laboratorio.
- `POST /{request_id}/aprobar` → acepta `{modo:"supervised"}` o `{modo:"timed",segundos:120}`; la aprobación debe ser transaccional contra ticket vigente, supervisor activo, exclusión de dueño, época y STOP autenticado.
- `POST /{request_id}/rechazar` → rechazo de esa solicitud, sin afectar otras.
- `POST /revocar` → revocación inmediata en el servidor, STOP prioritario y confirmación con política fail-closed. Nunca devolver `revocado:true` si el contrato no define claramente cómo se han invalidado las órdenes en curso.

Cada respuesta experimental requiere `simulado=true,control_fisico=false` y un booleano explícito de la acción; un HTTP 200 aislado no habilita nada. No mezclar el token de visitante con la X-API-Key. El origen oficial es `https://yori7v7.github.io`.

## Requisitos de seguridad antes de implementar realmente

- **Clave y laptop:** el cliente puede guardar X-API-Key solo en memoria, pero **el servidor** debe verificar la identidad/autoridad del dueño desde la laptop; el frontend no puede asegurar por sí mismo que la petición llegó de su equipo.
- **Turnos:** una sola autoridad para invitado, joystick administrativo, Swagger y DEMO; controlador persistente o recuperable tras reinicio y fencing de generación/epoch. K-G en memoria NO satisface producción multiworker.
- **Supervisión humana:** un latido automático en pestaña oculta no constituye evidencia humana real. Necesita señales adicionales de supervisión y parada segura por pérdida.
- **Límites:** validación estricta de origen/host detrás de proxy confiable, CORS adecuado, antiabuso, auditoría saneada, tiempo de sesión corto y tokens secretos nunca en URLs o logs.
- **STOP:** prioridad real sobre operaciones en vuelo, watchdog en ESP y pruebas supervisadas de estado mecánico neutro, no solo ACK HMAC de firmware con GPIO inhibidos.
- **Hardware:** ESP sigue en Wi-Fi de casa con batería del vehículo desconectada para laboratorio. El hotspot de examen se prepara después del software, pero se ensaya antes del examen.
- **Producto final:** el profesor recibirá solamente `https://yori7v7.github.io/control-iot-u4/`, sin introducir nada. Admin aprueba código del visitante desde su laptop en la misma página oficial.

**Nunca abrir el 8443 local a Internet ni desplegar el simulador K-G como producción. No modificar `main` ni activar `guestAdmissionEnabled`/`adminApprovalEnabled` todavía.**
