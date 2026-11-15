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


## Pasarela real WSS 55-I: cerrada a toda API HTTP

`scripts/servidor_55i_kv_kx_esp_lab.py` es un experimento de **dispositivo real,
salidas siempre en cero** que no se ejecuta automáticamente. Fue diseñado
para usar **únicamente** la identidad TLS/HMAC privada 55-H ya verificada.

- **Interfaz única:** se enlaza solo a la IP privada del hotspot registrada
  en `private/settings.json` (laboratorio probado: 172.22.82.209:8443).
- **Cliente único:** exige la IP 172.22.82.5 y Host exacto.
- **Red:** el wrapper ASGI `WssOnlyFromESP` contesta **HTTP 404 a TODAS
  las solicitudes**, incluso en el segmento del hotspot. Solo enruta el
  WebSocket `/ws/dispositivos-lab/1/contrato` desde el ESP autenticado.
- **Autoridad K-V:** el cliente de solicitud, aprobación y revocación está
  *dentro del mismo proceso Python* mediante `httpx.ASGITransport`; no
  hay ruta admin, API REST ni control de navegador expuesto al hotspot.
  Las pruebas crean secretos temporales **independientes** de producción
  y SQLite local efímero fuera del repositorio.
- **Secuencia de demostración:** STOP inicial autenticado, solicitud
  de invitado virtual, aprobación K-V, código 9 por K-X con ACKs HMAC,
  STOP 0, revocación y denegación de orden posterior.
- **Fallo cerrado:** si cambia la IP, falta la clave local de 32 bytes,
  el ESP no autentica o los ACK no se correlacionan, no se declara GO.
- **Firewall:** el módulo nunca modifica reglas; se requiere excepción
  de entrada estrictamente temporal por IP/puerto como en LAB 55-H.
- **Condiciones físicas:** **BATERÍA DEL RC DESCONECTADA**, ESP por USB,
  firmware 55-H solo diagnóstico, AWS/RDS apagados.

**No ejecutar todavía en producción ni configurar un proxy hacia este
servicio.** Primero aprobar todas las pruebas offline 55-I y auditar que
el firewall bloquea todo salvo el ESP. El comando del módulo es:

```powershell
& ".\\.venv\\Scripts\\python.exe" -m scripts.servidor_55i_kv_kx_esp_lab
```

El comando solo corresponde a una **ventana de laboratorio supervisada**,
nunca a un servicio Windows permanente. Los HTTP 404 del dispositivo
son intencionados: la interfaz HTTP no participa de la prueba.
La conexión directa del frontend GitHub Pages y una parada física
medida **siguen fuera del alcance**.
