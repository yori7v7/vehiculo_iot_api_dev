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

**Evidencia:** GitHub Actions [43375896468](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43375896468), commit `6b428ffc58d96285eb41e077a27b6e3410883e97`: **613 tests y 840 subtests aprobados**. Se ejecutaron solo en CI, no en la laptop del usuario.

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
