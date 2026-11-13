# 5.5-H — Evidencia del canal WSS directo ESP8266 ↔ servidor de laboratorio

**Resultado observado el 12/11/2026 en un NodeMCU ESP8266 real.** La etapa 5.5-H se ejecutó en una LAN local con un servidor Python HTTPS/WSS dedicado a diagnóstico. No se encendió AWS/RDS ni se activaron salidas físicas del 74HC595; la batería del vehículo permaneció desconectada.

## Evidencia reportada desde el Monitor Serie del ESP8266

```text
[55-H] MODO DIAGNOSTICO CON WSS LAN, SIN ACTUACION REAL
[54] Todos los bits enviados al 74HC595 se fuerzan a 0.
[55-H] TCP LAN ESP -> PC: OK (8443 accesible)
[55-H] TLS independiente ESP -> PC: OK (CA verificada)
[55-H] TLS WSS conectado; esperando desafio.
[55-H] Desafio recibido; HMAC de dispositivo enviado.
[55-H] TLS + autenticacion mutua HMAC: OK
[55-H] Orden 9 firmada: OK; GPIO inhibido, 250 ms virtuales.
[55-H] Neutral virtual firmado, no hay salida GPIO.
[55-H] DETENER 0 HMAC: OK, neutro virtual
[55-H] RESULTADO: WSS DIRECTO ESP8266 APROBADO - SIN MOTOR NI AWS
[55-H] WSS desconectado: salidas en NEUTRO.
```

**Conclusión confirmada:** el hardware ESP8266 estableció WSS sobre TLS con CA verificada frente al servidor LAN; completó la autenticación mutua HMAC; validó una orden diagonal virtual (código 9) y una orden de DETENER (código 0) firmadas. El posterior cierre de WSS dejó el neutro electrónico. Esto demuestra el flujo de dispositivo **directo por Wi-Fi** sin puente USB, a diferencia de la etapa 5.5-G.

## Incidencias y correcciones durante el diagnóstico

1. Un primer sketch no compilaba porque el diagnóstico llamaba a `GruaRC::detener()` (privado); se sustituyeron las llamadas externas por el método público de parada.
2. Los mensajes repetitivos de parada ocultaban el estado de red; se añadieron diagnósticos sin eliminar el bloqueo GPIO.
3. Se diagnosticó conexión Wi-Fi, conectividad TCP desde el propio NodeMCU, y luego la verificación TLS.
4. BearSSL rechazaba inicialmente el nombre del servidor (error 56); se regeneró el certificado LAN para una identidad compatible, sin desactivar CA.
5. La biblioteca WebSocket insertaba un encabezado `Origin` incompatible con la política del servidor de laboratorio; se corrigió la solicitud del cliente sin relajarla.
6. El servidor y el ESP8266 presentaron una divergencia de reloj de unos 25–26 ms; la verificación de DETENER aceptó en este laboratorio una tolerancia acotada de 100 ms, preservando HMAC, secuencia, época y TTL. **Esta modificación requiere revisión de seguridad antes de producir firmware apto para motores.**

## Límites de la evidencia

- Este firmware era un **diagnóstico con las salidas PC817 forzadas a cero**, NO un firmware listo para conducción.
- Aceptación de una orden y acuses HMAC **no prueban desplazamiento ni parada mecánica** del vehículo.
- La evidencia aportada corresponde al Monitor Serie del cliente ESP8266; el log final de la terminal del servidor no fue aportado por separado.
- Certificado, clave HMAC y dirección local son **solo de laboratorio**. Los archivos privados generados permanecen en el equipo local y NO deben subirse al repositorio público.
- Todavía NO se ha integrado esta sesión directa con el coordinador de control temporal admin/invitado, los endpoints públicos, el frontend GitHub Pages ni el despliegue de AWS.

## Siguiente hito

Implementar un canal de dispositivo de producción con credenciales provisionadas en privado, autenticación y protección contra repetición, arbitraje único de control admin/invitado, STOP prioritario y fail-safe. Después realizar pruebas físicas supervisadas y un ensayo completo desde GitHub Pages/AWS. Revisar la política de desfase de reloj para no aceptar movimientos futuros o caducados.

**La rama es experimental. Mantener el PR en borrador y no fusionarlo ni desplegarlo como control físico o público hasta completar los pasos pendientes.**
