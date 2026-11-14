# 5.5-K-A — Solicitud automática y aprobación manual para una única URL

**Decisión:** el profesor abrirá **https://yori7v7.github.io/control-iot-u4/** (URL oficial, sin `?modo=`, código de invitación ni segunda página). El frontend original conserva Control/Monitoreo, el joystick y Dark Red Premium. Ningún visitante debe escribir una clave.

## Prototipo de lógica aislada

- `app/public_control/single_link_admission_lab.py`: modelo en memoria que, en el futuro, permitirá registrar automáticamente un navegador al entrar. El navegador recibe un secreto temporal, un identificador y un código corto visible en pantalla; **sigue sin autorización de movimiento**.
- El administrador, después de autenticar su sesión, ve la cola y **elige explícitamente** qué navegador aprobar. No puede inferirse de forma segura que cualquier persona con la URL sea el profesor.
- El modo puede ser `timed` o `supervised` sin cuenta regresiva fija, pero solo mientras llega supervisión válida. El visitante recibe un bearer de turno diferente de X-API-Key; solo el titular del secreto de ese navegador puede consultar su autorización.
- Ante revocación, pérdida del dispositivo, salida del administrador o timeout de supervisión, el permiso se pierde; no se concede un nuevo turno mientras la capa de transporte no certifique un acuse de neutro lógico y vuelva a haber supervisión.
- No contiene rutas FastAPI, red, WSS, AWS, RDS, GPIO, Arduino ni despacho de órdenes. **No activa el vehículo.**
- `tests/test_single_link_admission_lab.py`: 9 pruebas unitarias del contrato en un entorno local, resultado **9 passed** (incluyendo rechazo de intento prematuro, aprobación exclusiva, caducidad de heartbeat, revocación, cola y retroceso de reloj).

## Componentes que todavía faltan

1. Implementar un **coordinador transaccional único** que arbitre y cierre también las rutas preexistentes de mando, DEMO y Swagger; sincronizar propietario/época/STOP con WSS autenticado. El modelo en memoria NO es apto para despliegue concurrente.
2. Crear HTTP de solicitud/estado/aceptación desde el mismo `index.html`, con límite de tasa, limpieza de tickets, validación de Origin, no-store, antifraude/CSRF y auditoría. Identificar al profesor mediante código visible comprobado presencialmente antes de aprobar.
3. Integrar solo los estados de UX en `control-iot-u4` sin redireccionar ni abrir un nuevo diseño. No habilitar joystick por defecto ni admitir control hasta recibir autorización fresca del único coordinador.
4. Asegurar STOP prioritario físicamente, watchdog de actuador y neutralidad ante caídas; probar sin motores, luego ensayo físico supervisado y finalmente prueba remota HTTPS con otra laptop.

**No publicar** credenciales, tokens ni certificados. El firmware permanece con GPIO 74HC595 inhibido y AWS apagado durante estas pruebas. El PR permanece draft y `main` intacta.

La rama paralela del frontend `feature/5-5k-portal-unico-invitado` registra el contrato de interfaz sin modificar todavía el sitio publicado.
