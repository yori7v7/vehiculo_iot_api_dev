# 5.5-J-C — Prueba manual HTTP de invitaciones en navegador

**Fecha reportada:** 12/11/2026, horario local. **Entorno:** paquete de laboratorio 5.5-J-C, servidor HTTP en `127.0.0.1:8766`, dos pestañas del navegador en la misma computadora.

## Resultado observado

Tras corregir la clave administrativa introducida inicialmente por error:

- Vista administrador: autenticación aceptada; respuesta `{"supervision":true,"vigencia_s":15,"control_fisico":false}`.
- El selector mostró **«Tiempo indefinido bajo supervisión»** y el formulario generó un enlace de un solo uso para `/demo?rol=invitado#invitacion=...` (se omite el token por seguridad).
- Vista invitado: mensaje **«Turno vigente (virtual)»** y respuesta `{"autorizado":true,"simulado":true,"control_fisico":false}`.
- La vista invitado mostró expresamente **«Joystick deshabilitado: la etapa solo comprueba permisos y revocación.»**

**Interpretación:** se validaron visualmente el acceso administrativo y el canje de invitación en dos pestañas locales, **sin API key en la vista invitado**. La restricción de motores y ausencia de despacho siguen activas.

## Pendiente

No se aportó todavía prueba visual de **revocación desde el panel y denegación posterior al invitado**. Tampoco existe acceso desde otro equipo, despliegue AWS/GitHub Pages del flujo de invitación ni conexión de este servidor HTTP al canal WSS del NodeMCU. No confundir permiso HTTP local con control físico.

**Seguridad:** no adjuntar ni registrar el enlace completo de invitación: contiene un token de canje. La evidencia de screenshots no se publica con ese token en el repositorio; este documento conserva solo resultados saneados. El PR permanece en borrador, sin cambios en `main`.
