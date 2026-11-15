# 55-I: K-V + K-X + protocolo 55-H (laboratorio virtual)

**Estado: borrador / prueba aislada. Sin despliegue AWS y sin control de motores.**

Este avance integra el módulo experimental `kv_kx_virtual_bridge_lab` (del
PR #8) con el handshake HMAC y formato de comandos del firmware ESP8266
`55-H`. Se ejecuta como ASGI **separado** del servicio original EC2 y
no cambia Caddy, RDS, tareas Windows, credenciales ni firmware.

## Compatibilidad del protocolo

- K-X original espera `Host: 100-30-4-62.nip.io` y WSS
  `/ws/kx-diagnostico/1`; el ESP8266 55-H usa el Host privado
  `172.22.82.209:8443` y `/ws/dispositivos-lab/1/contrato`.
- El modo 55-I permite configurar **host y peer exactos**, ambos IPv4
  privados en la misma subred /24; rechaza peers ajenos, orígenes web,
  autorización por header, parámetros de consulta, etc.
- El hub envía un STOP **virtual** HMAC inicial, y después de cada orden
  de movimiento confirmada vuelve a emitir STOP virtual. El dispositivo
  permanece con **74HC595=0** en la versión segura.
- K-V aplica aprobación, exclusividad, lease y revocación en el mismo
  coordinador virtual que realiza el envío WSS. La revocación invalida
  nuevas órdenes aun cuando un ACK antiguo llegue tarde.
- Nunca se presenta el ACK `neutral_reportado_no_fisico` como garantía
  de inmovilidad o STOP mecánico.

## Prueba offline (sin AWS, hotspot ni ESP)

Desde la rama `codex/55h-hotspot-seguro-sin-motores`, Python con deps
de desarrollo existentes:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -q tests/test_kv_kx_virtual_bridge_lab.py tests/test_55i_hotspot_bridge.py tests/test_55h_hotspot_server.py
```

Se usan IPs del hotspot **solo como entradas ficticias de TestClient**,
sin abrir puerto 8443. La clave del dispositivo en tests es pública y
ficticia; `private/` y el header local no se leen por los tests 55-I.

El modo LAN real **no está publicado ni autorizado para producción**.
Antes de una prueba por Wi-Fi real se requiere un arranque aislado que
sirva únicamente desde la interfaz hotspot, controle el puerto de
firewall por IP de dispositivo y asegure que las rutas de administración
no están disponibles para clientes LAN. No arrancar ASGI o crear reglas
de firewall como parte de estos tests.

## Límites y siguientes comprobaciones

- La suite CI comprueba HMAC/ACKs y la autoridad virtual K-V/K-X usando
  TestClient, pero no TLS real, Wi-Fi, neutral eléctrico ni parada física.
- El firmware 55-H termina su prueba de contrato y desconecta; para
  sesiones K-V continuas se deberá definir una versión de firmware
  de diagnóstico que permanezca conectada, sin habilitar GPIO.
- Si se pierde el transporte, el hub invalida autoridad WSS y se
  necesita nueva autenticación. Reinicio K-V invalida sesiones previas.
- La solución de SAN `dNSName` numérica de 55-H es compatibilidad de
  laboratorio y no sustituye identidad DNS válida para producción.
