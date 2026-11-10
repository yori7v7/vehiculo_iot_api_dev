# Firmware ESP8266 - Excavadora IoT AWS

Firmware final del dispositivo fisico Mini RC Forklift IoT basado en NodeMCU ESP8266, 74HC595 y optoacopladores PC817.

## Estado

Integracion fisica confirmada de extremo a extremo:

Swagger / FastAPI en AWS -> Amazon RDS -> WSS -> ESP8266 -> 74HC595 -> PC817 -> control remoto modificado -> vehiculo fisico.

## Hardware

- NodeMCU ESP8266 ESP-12E
- 74HC595
- PC817 individuales
- Control remoto original modificado
- Mini RC Forklift HJ2025-1D

### Pines

- D5 / GPIO14: DATA del 74HC595
- D6 / GPIO12: CLOCK del 74HC595
- D7 / GPIO13: LATCH del 74HC595
- D2 / GPIO4: reset de credenciales Wi-Fi manteniendo a GND 5 s

## Mapeo 74HC595

| Salida | Funcion | Codigo |
|---|---|---:|
| Q0 | AVANZAR | 1 |
| Q1 | RETROCEDER | 2 |
| Q2 | IZQUIERDA | 4 |
| Q3 | DERECHA | 8 |
| Q4 | LUCES | 16 |
| Q5 | VELOCIDAD | 32 |
| Q6 | DEMO_ORIGINAL | 64 |
| Q7 | CLAXON | 128 |

Combinaciones:

- AVANZAR_IZQUIERDA = 5 (Q0 + Q2) — ampliación del 09/11/2026
- RETROCEDER_IZQUIERDA = 6 (Q1 + Q2)
- AVANZAR_DERECHA = 9 (Q0 + Q3)
- RETROCEDER_DERECHA = 10 (Q1 + Q3) — ampliación del 09/11/2026
- DETENER = 0

## Arquitectura del firmware

El firmware conserva Programacion Orientada a Objetos mediante tres clases principales:

- `GruaRC`: encapsula control fisico, 74HC595, movimientos y comandos especiales.
- `GestorWiFi`: encapsula WiFiManager, persistencia, reconexion y reset de credenciales.
- `ClienteAWS`: encapsula WSS, ArduinoJson, TLS, eventos AWS, DEMO y fail-safe.

## Conectividad

- Endpoint WSS: `wss://100-30-4-62.nip.io/ws/vehiculos/1`
- Puerto: 443
- Validacion TLS X.509 mediante CA
- Sincronizacion NTP antes de abrir WSS
- Reconexion automatica

El evento `estado_actual` es informativo y nunca se ejecuta fisicamente al reconectar. Esto evita que un estado persistido antiguo reactive el vehiculo despues de un reinicio o perdida de red.

## Comandos fisicamente confirmados desde Swagger

- DETENER
- AVANZAR
- RETROCEDER
- IZQUIERDA
- DERECHA
- RETROCEDER_IZQUIERDA
- AVANZAR_DERECHA
- LUCES
- VELOCIDAD
- CLAXON

Los comandos especiales conservan su comportamiento de pulsacion.

## Ampliacion de ocho direcciones (09/11/2026)

El firmware agrega `AVANZAR_IZQUIERDA` (codigo 5) y `RETROCEDER_DERECHA` (codigo 10) al procesamiento de `movimiento` recibido de AWS, a los pasos `demo_movimiento` y al watchdog de 12 s. Se conservan las ocho salidas del 74HC595, los PC817, las reglas y comandos anteriores, el intervalo neutro de 30 ms y los fail-safe.

El 09/11/2026 se reporto compilacion exitosa con Arduino CLI 1.5.1, core ESP8266 3.1.2, y carga por COM4 (Only Sketch, 57 600 baudios tras un primer timeout, flash verificada). El Monitor Serie confirmo WSS conectado con certificado TLS validado; recibio y proceso ocho direcciones, entre ellas `codigo: 5` (`id_comando: 16`) y `codigo: 10` (`id_comando: 17`), ademas de DETENER. El frontend registro 27 pruebas Node y 15 Chrome aprobadas en simulacion/trafico interceptado.

**Alcance:** se verificaron mensajes WSS y despacho del firmware; todavia no se comprobo que el control remoto y el montacargas ejecuten fisicamente las dos combinaciones nuevas. La lista anterior de «Comandos fisicamente confirmados» corresponde a las pruebas originales, no a estas dos diagonales.

## DEMO dinamica AWS

La DEMO se obtiene desde el backend/RDS y no esta hardcodeada en el ESP8266.

Secuencia probada:

1. DETENER
2. AVANZAR
3. AVANZAR_DERECHA
4. RETROCEDER_IZQUIERDA
5. CLAXON
6. DETENER

El ESP8266 procesa `demo_movimiento`, aplica `duracion_ms` mediante `millis()` y detiene fisicamente la salida al finalizar cada duracion. La pausa queda respetada hasta que AWS envia el siguiente paso.

Tambien se confirmo fisicamente:

- `demo_fin` -> parada segura
- `demo_cancelada` -> parada inmediata
- `demo_error` -> parada segura

## Fail-safe confirmado

Se probo perdida real de Wi-Fi mientras el vehiculo estaba en AVANZAR.

Resultado:

1. Se detecto perdida de Wi-Fi.
2. El firmware ejecuto `paradaSeguridad()`.
3. El vehiculo se detuvo sin recibir DETENER desde Swagger.
4. El ESP8266 se reconecto automaticamente.
5. El WSS se restablecio.
6. AWS envio `estado_actual` con AVANZAR persistido.
7. El firmware lo ignoro fisicamente y el vehiculo no volvio a moverse solo.

## TLS

La version final utiliza validacion de certificado del servidor mediante `beginSslWithCA(...)` y sincronizacion NTP previa.

La conexion WSS con certificado validado fue comprobada antes de publicar esta version.

## Configuracion local obligatoria

El repositorio no contiene la contraseña real del AP de WiFiManager.

Antes de compilar, sustituir localmente:

```cpp
const char* AP_PASSWORD = "CONFIGURAR_LOCALMENTE";
```

por el valor usado en el dispositivo.

No subir contraseñas, API keys ni otras credenciales al repositorio.

## Librerias

- ESP8266WiFi
- WiFiManager
- WebSocketsClient
- ArduinoJson
- `time.h`

## Arduino IDE

Configuracion usada durante las pruebas:

- Placa: NodeMCU 1.0 (ESP-12E Module)
- Serial Monitor: 115200 baud
- Line ending recomendado: No line ending

## Seguridad

El firmware detiene el vehiculo ante:

- perdida de Wi-Fi
- desconexion WSS
- `demo_cancelada`
- `demo_error`
- codigo AWS desconocido

El firmware no almacena la API key administrativa del backend.
