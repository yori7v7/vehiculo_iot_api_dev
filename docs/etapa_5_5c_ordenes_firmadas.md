# Etapa 5.5-C — Contrato de orden/acuse firmado (SIN ACTUACIÓN)

Archivo `app/device_channel/command_wire.py` y pruebas unitarias
`tests/test_device_command_wire.py`.

**No existen aún conexiones con el despachador de turnos, firmware o motores.**
El WSS `/ws/dispositivos-lab/{id}` conserva su alcance de laboratorio y NO
transmite órdenes. El contrato solo serializa y verifica mensajes; está
aislado del control físico.

## Formato binario de orden

Paquete big endian de **68 bytes**, `>BI16s16sIIIQQHB`:

1. versión (1 byte, =1);
2. ID vehículo (uint32);
3. ID sesión de 16 bytes (el del handshake WSS autenticado);
4. UUID v4 de la operación (16 bytes);
5. generación, época, secuencia (uint32 cada uno);
6. emitido y vencimiento, tiempo Unix en milisegundos (uint64);
7. duración (uint16), código (uint8).

El sobre JSON lleva `tipo=orden_dispositivo_v1`, `sesion`,
`paquete` (base64url sin padding), `firma` (HMAC-SHA256 hexadecimal),
firmado con la clave `command_key` derivada de la autenticación.
La firma cubre el dominio fijo
`vehiculo-iot|device-order-v1|` seguido exactamente de los 68 bytes.

Solo ocho direcciones (1,2,4,5,6,8,9,10), con duración 100–500 ms,
y DETENER (0, duración cero). El plazo de entrega máximo es 1000 ms.
El consumidor debe tener reloj válido; el ESP aún no interpreta este
formato y no debe considerarse compatible hasta integrarlo y probarlo.

## Formato binario de acuse

Paquete big endian de **59 bytes**, `>BI16s16sIIIQBB`:
versión, vehículo, sesión, operación, generación/época/secuencia,
instante del dispositivo, fase (1 recibido, 2 neutral, 3 rechazado)
y bandera neutral. Firma HMAC sobre dominio
`vehiculo-iot|device-order-ack-v1|`, con `telemetry_key`.

`AckFence` exige coincidencia exacta de operación, sesión,
generación, época y secuencia; STOP de época superior desplaza MOVE
pendiente; un acuse desordenado o manipulado bloquea la sesión.
`physical_stop_verified` siempre vale `False`.
Un acuse de neutro del GPIO NO confirma por sí solo inmovilidad mecánica.

## Pruebas

`python -m pytest -q tests/test_device_command_wire.py`

**34 pruebas aisladas pasaron en Python** antes de subir los archivos,
incluidos HMAC independiente, integridad, límites, tiempo, repetición,
prioridad de DETENER y desconexión. La suite completa corre por GitHub
Actions en el PR: `.github/workflows/backend-ci.yml`.

## Pendiente antes de permitir al profesor manejar desde GitHub Pages

- Integrar estas tramas en un WSS **de producción**, separado del MONITOREO.
- Procesarlas en un firmware que valide certificado, autenticación mutua,
  HMAC, secuencia, vencimiento y detenga las salidas ante desconexión.
- Conectar todos los endpoints del administrador y los invitados a
  una **única** autoridad sobre movimientos y demos.
- Probar físicamente y definir criterios de parada/relevo supervisados.
- Verificar el comportamiento desde incógnito, sin API key, después
  de un despliegue autorizado y reversible.
