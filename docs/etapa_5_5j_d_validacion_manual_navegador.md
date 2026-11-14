# 5.5-J-D — Confirmación manual de panel automático en Windows

**Fecha:** 12/11/2026, hora de México (confirmación del usuario). **Estatus:** pruebas de comportamiento reportadas **correctas** en el navegador del alumno.

## Secuencia probada

El usuario instaló la corrección HTML 5.5-J-D sobre el servidor HTTP local 5.5-J-C y realizó el flujo recomendado:

1. Autenticarse como administrador, activar supervisión y generar nueva invitación.
2. Abrir la invitación en otra pestaña como invitado (sin API key).
3. Mantener al invitado abierto mientras la pestaña del administrador está en segundo plano, evitando la caducidad espuria que afectaba 5.5-J-C.
4. Revocar desde el panel del administrador y comprobar que la pestaña del invitado se actualiza sola, sin pulsar «Actualizar permiso».

El usuario respondió **«todo funciono bien»**. Es confirmación manual cualitativa; no se compartieron nuevas marcas de tiempo, logs o trazas de red. **No se inventan métricas de latencia**.

## Alcance y límites

Aprobado: UX de **autoactualización de autorización y supervisión entre dos pestañas locales**.

No probado: acceso del profesor desde otra computadora, GitHub Pages conectado con el servidor, AWS, integración con el WSS del NodeMCU dentro de un mismo coordinador, presencia humana verificada o movimientos físicos. Demo HTTP enlazada exclusivamente a localhost, joystick deshabilitado; firmware real del ESP8266 5.5-H mantiene 74HC595 y PC817 forzados a neutro. El heartbeat de una pestaña oculta sirve a la demostración local, pero **no verifica que el administrador esté presente**.

**Siguiente hito:** validar la integración de una fuente única de autorización y despachador WSS seguro en laboratorio sin actuadores; solo después diseñar despliegue remoto, turnos reales por enlace y watchdog físico.

**No publicar los enlaces con tokens efímeros de prueba, claves, certificados o archivos privados. Mantener PR en borrador y `main` intacta.**