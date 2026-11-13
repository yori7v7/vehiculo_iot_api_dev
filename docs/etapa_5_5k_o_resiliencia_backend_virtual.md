# Etapa 5.5-K-O — Resiliencia del modelo de admisión (laboratorio virtual)

**Estado:** seis pruebas nuevas del modelo de admisión aprobadas en la rama experimental. No es validación física ni prueba WSS de desconexión con el ESP8266. EC2/RDS apagados; GPIO inhibidos, batería desconectada.

## Objetivo

Verificar desde el **servidor** que la expiración, la caída de supervisión, la pérdida del dispositivo y la aprobación concurrente con revocación no restablezcan permisos lógicos sin un STOP virtual confirmado. Las comprobaciones del navegador K-N **no** sustituyen estos invariantes.

## Casos automatizados

Archivo `tests/test_ko_resilience_lab.py`, sin conexión a red ni actuadores:

1. Ticket de visita caducado a los 120 segundos nunca puede aprobarse.
2. Ausencia de latido administrativo durante 15 segundos termina un turno supervisado y obliga a confirmar neutro virtual antes de habilitar otro.
3. Turno de 30 segundos caduca aunque el supervisor envíe latidos cada diez segundos.
4. Desconexión simulada del dispositivo revoca sesiones anteriores, incrementa generación y bloquea nuevas aprobaciones hasta confirmar neutro.
5. Retroceso del reloj monotónico simulado invalida los permisos.
6. Aprobación y revocación concurrentes, serializadas por **el mismo lock**, no dejan un invitado activo cuando ambas operaciones terminan.

**Evidencia actualizada:** GitHub Actions [43376205256](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43376205256), commit `ff8470be2240417afb044a9bf88df8abff87d785`: **614 tests y 840 subtests aprobados** (incluye comprobación de sintaxis y método GET único del guion manual). Se ejecutaron solo en CI, no en la laptop del usuario.

## Lo que aún falta para cerrar K-O

- Ejecutar con el firmware 55-H de diagnóstico en USB (batería y PC817 físicos aislados) la desconexión/reconexión WSS del ESP ante un servidor K-G real, con una autorización virtual que quede invalidada y sin reapertura automática.
- Comprobar que el backend niega nuevas operaciones tras reconexión hasta un nuevo handover seguro. No reiniciar automáticamente un invitado anterior.
- Probar cancelación de un POST `aprobar` en vuelo al desconectarse el ESP y concurrencia real entre `aprobar` y `revocar` con el controlador K-C. Las pruebas de modelo no reproducen HMAC/TLS, red ni E/S física.
- Para producción: fencing interproceso, almacenamiento durable, rate limiting, dispositivo con watchdog autónomo, parada mecánica verificada y única autoridad WSS para movimiento/DEMO/Swagger. **No exponer K-G ni habilitar GitHub Pages remoto todavía**.

## Reglas de operación

- Mantener las ramas `main` sin modificar y PR #5 en borrador.
- No abrir 8443 en router ni usar AWS/RDS.
- No conectar batería ni probar motores durante K-O.
- STOP firmado HMAC del ESP indica **neutro virtual únicamente**, no parada física.

## Guion manual de desconexión / reconexión (pendiente)

Se añadió `scripts/prueba_55ko_reconexion_local.py`, que importa la utilidad HTTPS K-K antes validada por el alumno en Descargas. El script únicamente realiza `GET` administrativos con TLS y verificación de IP. **No ejecuta todavía esta prueba por sí solo**: el operador interviene manualmente:

1. **Terminal 1:** K-G conectado al ESP8266, con log de autenticación y STOP HMAC virtual. La fase inicial exige HTTP 200, lista pendiente vacía, ningún turno activo y `control_fisico=false`.
2. **Terminal 2:** NodeMCU alimentado solamente por USB, batería del vehículo desconectada, GPIO y PC817 inhibidos. Después de confirmar un estado limpio, desconectar SOLO el USB del ESP.
3. **Terminal 3:** el guion espera HTTP 503 al detectar pérdida WSS. Luego pide reconectar USB, confirmar nuevo log de autenticación y STOP virtual en Terminal 1, y verifica que el GET administrativo permanezca HTTP 503: **no debe reabrirse automáticamente por reconectar el ESP**.
4. Para repetir ensayos anteriores K-L, reiniciar K-G de forma controlada y exigir un nuevo handover verificado.

Este guion está **pendiente de ejecución humana** y no demuestra bloqueo mecánico, ni reemplaza una prueba de STOP físico con un interlock independiente. Si no devuelve 503 después de la desconexión, detener la secuencia y revisar K-G; jamás forzar su apertura.

## Incidencia real K-O observada el 13/11/2026 y corrección experimental

El alumno ejecutó `scripts/prueba_55ko_reconexion_local.py` en Windows con servidor K-G y NodeMCU ESP8266:
- **Fase 1 aprobada:** GET admin HTTP 200 sin turnos ni pendientes; TLS 1.3 con certificado e identidad IP válidos; el servidor había confirmado STOP inicial virtual HMAC.
- **Fase 2 falló:** tras desconectar el USB según la ejecución informada, el script observó HTTP 200 repetidamente durante toda su ventana de aproximadamente 15 s. No se ejecutó la fase 3. En terminal se vieron tres `WireProtocolError` iniciales y después `ESP autenticado; STOP inicial virtual con HMAC OK`, sin evidencia de cierre posterior.

**Diagnóstico técnico:** K-G confiaba en `controller.connected`; dicho indicador puede permanecer verdadero si el TCP/WSS no informa oportunamente una pérdida abrupta (o si el dispositivo continúa alimentado). **No quedó comprobado cuál de esas causas ocurrió realmente en la laptop.** Se requiere verificar liveness a nivel de mensajes autenticados, no inferir que un TCP abierto equivale a un ESP operativo.

**Parche en la rama experimental solamente:**
- Nuevo `app/public_control/kg_liveness.py`: préstamo temporal de un ACK HMAC reciente, vencimiento máximo de 8 s y cierre irreversible de la sesión experimental.
- `app/public_control/kg_bootstrap.py`: tras un handover firmado correcto, cada 2 s solicita un **nuevo STOP virtual código 0** al único `KCController`, bajo su `asyncio.Lock`, con timeout de 2.5 s. Solo el retorno satisfactorio con dos ACK HMAC comprobados permite renovar el préstamo. Ante timeout/acuse inválido/desconexión, bloquea inmediatamente K-K/K-I/K-F, invalida el modelo de invitaciones y pide cierre del transporte; no reabre sin reiniciar K-G y un handover nuevo.
- `ki_ingress.py`, `kk_admin_lab.py`, `kf_bridge.py`: comprueban además que la última verificación HMAC no esté vencida, aunque `controller.connected` continuara True.
- Pruebas de regresión: respuesta HMAC perdida con TCP aparentemente abierto, recepción WSS bloqueada sin cierre, bloqueo persistente tras simular reconexión y préstamo vencido.

**Evidencia CI:** [ejecución 43378217865](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43378217865), commit `4d335f5f2ab57568c1a49e3b923eb4026148b325`: **617 pruebas y 840 subpruebas aprobadas**. Estas pruebas emplean un KC virtual: **no garantizan que el código local privado `servidor_55kc.py` acepte el nuevo sondeo con ESP físico**. Si este controlador no devuelve HMAC para cada STOP, el sistema fallará cerrado y debe revisarse, nunca saltarse la comprobación.

**Resultado físico actual de K-O:** NO APROBADO; retest pendiente en laptop tras `git pull --ff-only`, con firmware diagnóstico realmente grabado, GPIO/PC817 inhibidos, batería fuera y AWS/RDS apagados. Solo lectura HTTP desde el script. Si la fase 1 no llega a HTTP 200 después del nuevo arranque, detener el ensayo y reportar los logs sin claves; si la fase 2 sigue HTTP 200 tras desconectar USB, comprobar si el ESP sigue encendido por otro cable o fuente y suspender el trabajo de control remoto.
