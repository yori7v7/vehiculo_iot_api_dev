# 5.5-I-A — Turnos locales sobre WSS directo (laboratorio)

**Estado: implementado y probado con dispositivo virtual; pendiente prueba con ESP8266 físico.**

## Objetivo

Reutilizar el **firmware 5.5-H ya cargado**, el certificado TLS y la clave HMAC local sin regenerarlos. El firmware 5.5-H procesa varias órdenes firmadas en una misma sesión, aunque el servidor 5.5-H original solamente emitía diagonal 9 + DETENER 0 y cerraba.

Se preparó un servidor local de laboratorio `servidor_55i.py` y cliente de consola `cliente_55i.py`, entregados como ZIP independiente para instalarse junto al laboratorio 5.5-H existente. **No requieren subir otro sketch**. La carpeta `private/` permanece exclusivamente en la PC del alumno.

## Contrato operativo de laboratorio

- El NodeMCU entra por `/ws/dispositivos-lab/1/contrato` con la misma CA y autenticación mutua HMAC que en 5.5-H.
- Un servidor mantiene una **única conexión de dispositivo**, una cola de telemetría firmada y un despacho serializado.
- Inicio de sesión: DETENER firmado y correlacionado.
- Operadores de prueba `admin` y `guest`, tokens privados **diferentes**, llamados únicamente desde la **misma PC**. No se aceptan accesos externos del navegador.
- Administrador concede al invitado un turno de **1–30 segundos**, precedido de DETENER firmado. Durante su turno las órdenes del administrador se rechazan (salvo DETENER administrativo).
- Movimientos limitados a códigos `1,2,4,5,6,8,9,10` y duración `100–500ms`. Cada movimiento envía automáticamente DETENER firmado; se verifica HMAC de recepción y de neutro lógico.
- Orden con firma incorrecta, falta de acuses o desconexión: cierre de sesión, bloqueo y regreso a la condición de laboratorio.
- El DETENER administrativo queda serializado detrás de una operación en vuelo de duración máxima 500 ms. **Todavía no se implementó ni comprobó preempción física de emergencia.**

## Pruebas automatizadas del prototipo (12/11/2026)

**3 pruebas pytest aprobadas**, incluida una sesión WebSocket ASGI completa con dispositivo virtual autenticado y secuencia:

1. STOP inicial;
2. orden del administrador código 5 y STOP automático;
3. cesión al invitado precedida de STOP;
4. administrador rechazado mientras el invitado tiene el turno;
5. código 9 de invitado y STOP automático;
6. DETENER administrativo y recuperación de turno.

Otras comprobaciones: autenticación de tokens, rechazo a cliente distinto de la PC local, códigos/duraciones inválidos, vencimiento de invitado y firma incorrecta en ACK que cierra la sesión.

## Limitaciones esenciales

**No equivale a permitir conducir al profesor por Internet.** Esta versión es un experimento local y no forma parte de los endpoints AWS de producción ni de GitHub Pages.

- Los resultados de esta etapa provienen de **dispositivo virtual en pruebas**: falta el ensayo dinámico con ESP8266 físico del alumno.
- El firmware del ESP8266 debe mantener `ETAPA54_DIAGNOSTICO_SEGURO=1`, que fuerza 74HC595 a cero. **La batería del vehículo permanece desconectada**.
- Los acuses se refieren solo a un neutro *virtual/electrónico* y no demuestran detención mecánica.
- Las claves privadas, credenciales de Wi-Fi y certificados permanecen en `private/` y `config_55h_local.h`, nunca en GitHub.
- Antes de producción faltan control de autorización externo, turnos remotos por navegador, arbitraje con rutas administrativas heredadas, canal AWS seguro, watchdog y STOP prioritario real, además de pruebas físicas.

**No fusionar este PR con main como control público real.**
