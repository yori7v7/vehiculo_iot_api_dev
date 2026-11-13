# 5.5-K-C — Prueba manual con ESP8266 físico conectado (sin motores)

**Fecha:** 12 de noviembre de 2026, México; evidencia de tres terminales PowerShell enviada por el usuario.

## Preparación y autenticación

Terminal 1: `INSTALAR_55KC_WINDOWS.ps1` confirmó instalación de archivos nuevos sin modificar `55-J`, firmware ni `private`. `py .\\servidor_55kc.py` publicó en LAN `192.168.1.82:8443` con HTTP de operadores restringido a la misma PC. Registro observado:

```text
[55-K-C] COORDINADOR ÚNICO DE LABORATORIO — SOLO VIRTUAL
[55-K-C] ESP autenticado; STOP inicial virtual con HMAC OK
```

Terminal 2: `cliente_55kc.py vigilar` imprimió reiteradamente `Supervisión aceptada` (esperada cada 5 s; timeout configurado 15 s).

## Flujo de solicitudes y permisos

Terminal 3:

```text
solicitar        -> estado=esperando_autorizacion, display_code=A5676F13
pendientes       -> request_id=a5676f13-ba6e-4614-a5e2-7b8965d528bf, vence_en_seg=120
aprobar          -> aprobada=true, modo=supervised, simulado=true, control_fisico=false
estado-visitante -> estado=autorizado, display_code=A5676F13
mover-admin 1    -> HTTP 409, "No tienes el turno exclusivo"
mover-visitante 9 -> aceptada=true, codigo=9, simulado=true, neutral_virtual=true, motor=false
detener          -> detener=true, neutral_virtual=true, parada_fisica_verificada=false
estado-visitante -> estado=revocado_o_caducado
mover-visitante 9 -> HTTP 409, "No tienes el turno exclusivo"
mover-admin 1     -> aceptada=true, codigo=1, simulado=true, neutral_virtual=true, motor=false
estado           -> etapa=5.5-K-C, dispositivo_autenticado=true, operador=admin,
                    modo_turno=administrador, gpio_inhibido=true,
                    unico_despachador_wss=true, acceso_profesor_remoto=false,
                    supervision_vigente=false, supervision_ttl_s=0
```

**Veredicto de laboratorio:** aprobado el flujo completo con el **ESP8266 físico autenticado** y respuesta virtual de orden diagonal 9 / STOP, exclusión del administrador, revocación y recuperación administrativa. **No hubo motor en funcionamiento**.

## Por qué el último estado de supervisión es false

Revisado el código base `servidor_55j.py` heredado por K-C: en `LabController.status()`, el campo `supervision_vigente` se calcula como `bool(running and self.supervised)`, donde `running` solo es verdadero si el operador activo es `guest`. Por tanto **cuando el estado es `operador=admin`, se muestra `supervision_vigente=false` aunque el proceso `vigilar` siga emitiendo pulsos**. Ese campo indica *turno invitado supervisado activo*, no *latido administrador recibido recientemente*. Este resultado **no implica** por sí solo pérdida de conectividad. Es recomendable exponer por separado la salud del latido del administrador antes de integrar el frontend final.

## Límites explícitos

- El STOP firmado y los ACK son de **neutro virtual**, no una prueba de parada mecánica; el firmware exige GPIO inhibidos, batería del vehículo desconectada.
- La prueba manual no demuestra prioridad física/preemptiva de STOP ni valida la resistencia de todas las rutas legacy REST/Swagger de AWS; K-C solo controla sus rutas locales.
- No hay acceso externo desde GitHub Pages, integración con producción AWS/RDS, puente de hotspot ni segunda computadora.
- El carácter del display_code y UUID son identificadores de solicitud de laboratorio, no contraseñas; se omiten secretos/token navegador/HMAC.
- El usuario no aportó captura del Monitor Serie en esta ejecución, así que no afirmar evidencia adicional de ese registro.

**Siguiente fase:** auditar y cerrar caminos alternativos de movimiento heredados, definir estados API operativos y conectar rol invitado al frontend oficial sin abrir acceso físico prematuramente. Mantener los PRs como borrador y ambas ramas `main` intactas.
