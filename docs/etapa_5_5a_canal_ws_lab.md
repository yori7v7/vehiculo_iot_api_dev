# Etapa 5.5-A — Canal WSS de dispositivo autenticado (LABORATORIO)

> **No apto para producción ni para controlar el vehículo físico.**

Se añade un canal separado del WebSocket público de MONITOREO:
`/ws/dispositivos-lab/{id_vehiculo}`. Autentica un dispositivo virtual mediante
desafío HMAC-SHA256 con clave secreta, derivación de claves de sesión y
confirmación mutua. Solo acepta telemetría **simulada**, con código de salida
virtual cero, neutral virtual y contador creciente. No transmite órdenes.

## Activación local

DEVICE_LAB_ENABLED es false por defecto. Al habilitarla, APP_ENV debe ser
development y DEVICE_LAB_KEY debe contener una clave privada aleatoria de
32 bytes codificada en Base64url canónico sin padding. Nunca almacenar claves
reales en Git, JavaScript público, logs ni archivos de documentación.
En producción o simultáneamente con los turnos públicos, la configuración
falla cerrada.

Ejecutar solo directamente en 127.0.0.1 y sin proxy inverso o túneles:
`uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1 --no-proxy-headers`.
Se comprueban IP y Host locales, sin Origin ni query string. Estas
restricciones NO convierten el laboratorio en una configuración productiva.

## Protocolo

- Servidor emite desafio_dispositivo_lab con nonce aleatorio de 32 bytes.
- El cliente entrega autenticar_dispositivo_lab con prueba HMAC ligada al
  vehículo, al desafío y a los nonces de dispositivo y arranque.
- El servidor entrega dispositivo_autenticado_lab y prueba mutua; se
  derivan claves de sesión diferentes para cada dirección.
- La telemetría_dispositivo_lab debe llevar sesión exacta, contador
  creciente, salida virtual en cero y HMAC de sesión.
- El servidor entrega telemetria_recibida_lab firmado.
- No hay conexión con el coordinador físico, RDS ni comandos de motor.

## Pruebas

`python -m pytest -q tests/test_device_channel_lab54d.py tests/test_device_channel_lab_ws.py tests/test_device_lab_settings.py`

46 pruebas aisladas aprobadas. La suite completa del repositorio no se ha
ejecutado en este entorno. No se utilizaron COM, AWS ni motores.

## Pendiente antes del acceso real del profesor

1. Credenciales rotables por dispositivo y protocolo de producción.
2. Firmware ESP8266 que autentique el servidor y rechace órdenes antiguas,
   aplique duraciones máximas y mantenga parada independiente del navegador.
3. Unificar en un solo coordinador las órdenes del administrador, invitados
   y DEMO, y correlacionar operaciones del backend con acuses físicos.
4. Comprobar la parada física: un ACK de neutral virtual no prueba inmovilidad.
5. Pruebas de banco, ensayos supervisados, autorización del despliegue AWS
   y plan de reversión.

NO habilitar movimiento público físico ni desplegar el canal lab en AWS.
