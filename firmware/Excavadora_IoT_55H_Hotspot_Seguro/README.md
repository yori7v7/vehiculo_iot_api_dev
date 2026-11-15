# 55-H Hotspot Seguro — candidato ESP8266 de laboratorio, sin motores

**Estado:** código de prueba aislado, sin publicación, sin movimiento físico. No es aún la versión física final. Conserva el handshake de desafío y autenticación mutua HMAC, el WSS con CA y los dos acuses firmados del laboratorio 55-H. El ESP jamás puede energizar una salida del 74HC595: la única llamada \`shiftOut\` usa un literal cero. El selector de las ocho direcciones es **virtual**, no un motor.

## Hardware / mapa teórico

- NodeMCU ESP8266 (core **3.1.2**), 74HC595 y PC817.
- D5/GPIO14 → DATA; D6/GPIO12 → CLOCK; D7/GPIO13 → LATCH.
- D2/GPIO4 → GND 5 s para borrar Wi-Fi; entrada \`INPUT_PULLUP\`.
- Q0 avance (1), Q1 retroceso (2), Q2 izquierda (4), Q3 derecha (8).
- Combinaciones virtuales: 5, 6, 9, 10. STOP=0.
- Las salidas Q4…Q7 y DEMO no son actuadas en este firmware; el proyecto físico anterior sigue resguardado y no se modifica.
- Al iniciar, desconectarse, recibir STOP y vencer el plazo virtual, se escribe cero.
- No acepta W/S/A/F ni comandos físicos seriales. Por Serial solo \`R\` restablece Wi-Fi y \`0\` fuerza neutro.

## Hotspot celular 2.4 GHz

WiFiManager utiliza \`EXCAVADORA-<chipid>\`, portal \`192.168.4.1\` y clave WPA2 privada generada localmente. El nombre y contraseña del **hotspot del teléfono** se introducen por el portal cuando el ESP se configure; no están en el \`.ino\`. Conviene usar la laptop conectada al AP temporal del ESP u otro teléfono, ya que muchos móviles no pueden compartir hotspot y conectarse a otro AP a la vez.

El hotspot debe compartir Internet para NTP y permitir comunicación entre el ESP y la laptop (aislamiento de clientes desactivado). La laptop debe unirse al mismo hotspot para que el WSS LAN privado de prueba sea accesible. Cambiar el SSID/clave del teléfono permite reconfiguración WiFiManager usando el reset D2 / Serial R, con batería del vehículo desconectada.

## Identidad privada y montaje LAB (no ejecutar hasta que se autorice la prueba USB)

Instalar \`cryptography\` en un entorno local privado y desde la raíz del repositorio:

\`\`\`powershell
py scripts\preparar_55h_hotspot_seguro.py --host IP_PRIVADA_LAPTOP
\`\`\`

El script solicita **una nueva clave de acceso del AP ESP**, no la contraseña del hotspot. Genera archivos ignorados por Git \`firmware/Excavadora_IoT_55H_Hotspot_Seguro/config_55h_local.h\` y \`firmware/Excavadora_IoT_55H_Hotspot_Seguro/private/\`. La CA de prueba vence después de 7 días. **No compartir** HMAC, claves o certificados privados. Cada regeneración obliga a reinstalar firmware y reiniciar el servidor de prueba con las mismas claves.

Para la prueba local WSS 55-H, se requiere \`servidor_55h.py\` y \`app/device_channel/\` del paquete anterior, adaptados a usar el nuevo \`private/\` local del sketch. El endpoint del firmware es \`/ws/dispositivos-lab/1/contrato\` en el puerto TCP 8443 y certificado emitido para la IP privada indicada al generador. No habilitar firewall público, router NAT ni puertos accesibles desde Internet. Esta rama **no** incluye un servidor LAN nuevo ni activa ningún servicio AWS.

## Integración con permisos: límite crítico

El PR independiente de puente K-V + K-X (\`codex/kv-kx-puente-virtual-aislado\`) es **solo TestClient/loopback**, no acepta conexiones WSS desde ESP a través de hotspot ni emite órdenes de motores. K-V en EC2 declara \`canDrive=false\`. Este firmware aún no enlaza el portal del invitado con el vehículo físico.

Para funcionamiento físico posterior son necesarios: autoridad exclusiva de turnos y despacho firmado de producción, interlock de actuación independiente, fail-safe/STOP local medido, bloqueo de rutas legacy y pruebas reales con batería desconectada. Los ACK virtuales no acreditan parada mecánica.

## Condiciones de aceptación de esta etapa

1. Pruebas automatizadas \`tests/test_55h_hotspot_firmware_safety.py\` aprobadas.
2. Compilación Arduino NodeMCU ESP8266 aprobada sin cargar dispositivo.
3. Revisión de datos privados y restricciones.
4. Después, y solo con aviso explícito, conexión USB del ESP con batería desconectada.

Hasta completar esas condiciones, **NO conectar ESP ni batería y mantener AWS/RDS apagados**. No cambiar \`main\`, Caddy ni el firmware físico anterior.

## Servidor WSS local que reutiliza la identidad del firmware ya cargado

El script `scripts/servidor_55h_hotspot_seguro.py` **lee sin regenerar**
la identidad de `firmware/Excavadora_IoT_55H_Hotspot_Seguro/private/`.
Usa el HMAC y el certificado que ya generó la laptop antes de subir
el sketch al ESP. No volver a ejecutar el generador de secretos a menos
que se vaya a recompilar y volver a flashear el ESP.

Tras actualizar la rama local (`git pull --ff-only`) y crear un entorno
virtual de Python con FastAPI y Uvicorn, desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m scripts.servidor_55h_hotspot_seguro
```

Solo escucha en el IP privado configurado en `settings.json` y el puerto
8443. No abre firewall, Caddy, router, Internet, AWS, RDS ni actuadores.
Comprueba Host/origen/subred, autenticación HMAC, ACK y STOP **virtuales**.
Las pruebas de firmware y backend deben pasar antes de ejecutar en USB.

Si continúa inaccesible con el servidor ya escuchando, revisar conectividad
y firewall local con alcance restringido al hotspot. Si cambia la IP de la
laptop respecto al certificado, detener y planificar la rotación conjunta
de identidad y nuevo firmware.
