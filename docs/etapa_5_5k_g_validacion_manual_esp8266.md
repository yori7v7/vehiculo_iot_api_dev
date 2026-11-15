# 5.5-K-G — Validación manual con NodeMCU físico (solo protocolo virtual)

**Fecha:** 12 de noviembre de 2026, hora local México. **Origen de evidencia:** salidas de tres terminales PowerShell enviadas por el alumno. **Resultado: aprobado el flujo K-G de autorizaciones y WSS en la misma instancia FastAPI.**

## Terminal 1 — servidor

Se inició el backend experimental por `scripts/servidor_55kg.py` desde `Etapa_5_5_K_G_Backend_Experimental` usando el Python de su entorno `.venv`. Registro:

```text
[55-K-G] FASTAPI + WSS K-C en UN ASGI, diagnostico virtual
[55-K-G] LAN: 192.168.1.82:8443. HTTP operador SOLO desde esta PC.
[55-K-G] REST legacy bloqueado; AWS/RDS apagados; bateria desconectada.
[55-K-G] No abrir 8443 en router ni Internet.
[55-K-C] ESP autenticado; STOP inicial virtual con HMAC OK
```

## Terminal 2 — supervisión

`cliente_55kg.py vigilar` envió heartbeats de supervisión cada 5 segundos y registró repetidamente `[55-K-G] Supervisión aceptada` sin error.

## Terminal 3 — solicitud, autorización, STOP

```text
estado           -> etapa=5.5-K-F, dispositivo_autenticado=true,
                    operador=admin, gpio_inhibido=true,
                    unico_despachador_wss=true,
                    integracion=mismo_controlador_wss,
                    control_fisico=false
solicitar        -> esperando_autorizacion, display_code=1799B13E
pendientes       -> ticket 1799b13e-5c5c-43ce-9568-30c85d9e595f, vence_en_seg=120
aprobar          -> aprobada=true, modo=supervised, simulado=true
estado-visitante -> autorizado
detener          -> detener=true, neutral_virtual=true,
                    parada_fisica_verificada=false
estado-visitante -> revocado_o_caducado
```

**Interpretación:** el valor `etapa=5.5-K-F` identifica la puerta interna que K-G montó en el mismo ASGI; no significa que se haya iniciado el servidor antiguo. `supervision_vigente=false` en el primer `estado` es esperado mientras `operador=admin`: el campo heredado describe un turno de invitado supervisado activo, no la recepción del latido administrativo.

## No probado en esta ejecución

- No hay evidencia en K-G de movimiento virtual solicitado mediante `cliente_55kg.py`, solo solicitud, aprobación, STOP y revocación. K-C anterior sí probó MOVE 9 virtual y bloqueo del administrador, sin motores.
- No se aportaron nuevas trazas del monitor serie ni medidas eléctricas que prueben que los GPIO físicos están en cero; se reporta el flag diagnóstico `gpio_inhibido=true` y se conserva la precaución de batería desconectada.
- No existe acceso al servidor desde la laptop del profesor ni desde GitHub Pages; K-G restringe HTTP a la PC propietaria.
- No fue probada la parada mecánica; HMAC STOP solo confirma neutro lógico.

**Conclusión:** K-G se valida con NodeMCU real a nivel de WSS/autorización. Mantener rama de desarrollo y PR borrador. No activar actuadores ni AWS hasta consolidar autoridad única pública HTTPS, interlocks de STOP y ensayo de red/seguridad. La página oficial compartida para el examen será únicamente `https://yori7v7.github.io/control-iot-u4/`.
