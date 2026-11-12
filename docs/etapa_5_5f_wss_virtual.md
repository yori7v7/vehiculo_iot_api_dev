# Etapa 5.5-F: prueba de WSS firmado de extremo a extremo (solo dispositivo virtual)

## Qué valida

Nuevo endpoint `/ws/dispositivos-lab/1/contrato`, separado de MONITOREO y
apagado por defecto. Un cliente virtual hace desafío HMAC, verifica el
servidor, recibe una orden firmada `codigo=9` (diagonal) con vencimiento,
devuelve dos acuses HMAC, recibe `codigo=0` (DETENER) de época superior y
devuelve otros dos acuses. Al terminar el servidor cierra la sesión.

Las órdenes se envían con el mismo formato binario de **68 bytes** y los
acuses con el de **59 bytes** validados en Arduino por USB durante 5.5-E.
En esta fase, el cliente WSS sigue siendo **Python**, no el firmware.
**No existe capacidad de actuación física; este endpoint es de laboratorio.**

## Prueba local en Windows PowerShell

1. Obtener la rama `feature/5-5a-dispositivo-protocolo-aislado` del backend
   (NO `main`); ejecutar los siguientes comandos desde su directorio raíz.
2. Crear dos terminales PowerShell distintas.
3. En la primera, preparar las variables de entorno *en esa sesión*:

```powershell
py -m pip install -r requirements-dev.txt
$env:APP_ENV = 'development'
$env:DEVICE_LAB_ENABLED = 'true'
$env:DEVICE_LAB_KEY = py -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))"
py -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1 --no-proxy-headers
```

4. En la segunda terminal copiar el secreto privado de la **primera sesión**
   sin mostrarlo en capturas ni guardarlo en el repositorio. Se puede iniciar
   el servidor y el cliente desde **una sola ventana de PowerShell** poniendo
   el servidor en otro proceso que herede `DEVICE_LAB_KEY`, para evitar copiar
   el secreto. Nunca subir claves reales a GitHub.
5. Ejecutar `py -m scripts.prueba_wss_55f` con el mismo `DEVICE_LAB_KEY`.
6. Buscar la línea final:

```text
[55-F] RESULTADO: WSS BINARIO APROBADO - SIN MOTOR NI AWS
```

**Alternativa** para dos terminales: crear la clave una vez en un archivo
privado de usuario, asignarla manualmente en cada terminal y eliminar dicho
archivo al acabar. El archivo debe permanecer fuera del proyecto; no incluirlo
en capturas ni documentación de entrega.

## Invariantes

- El endpoint solo admite cliente loopback y `Host` local, desarrollo, sin
  proxy, cookies de navegador ni `Origin`. No utilizarlo desde AWS.
- El dispositivo tiene que presentar su clave privada (HMAC), usar un desafío
  único, comprobar la firma del servidor y confirmar sesión.
- Se rechazan cambios a datos firmados, reenvíos de acuses, operaciones ajenas,
  sesiones simultáneas y timeouts. La conexión cierra con error al fallar.
- `parada_fisica_verificada` siempre es `false`.
- No se registra ninguna orden en RDS, SQLite ni hardware.

## Próximo paso real

Conectar el firmware ESP8266 WSS a un endpoint **de dispositivo productivo**
con credencial privada, conservar el WSS público solo para MONITOREO, unificar
las órdenes de administrador/invitados, ejecutar pruebas con batería desconectada
y por último validar el movimiento y la parada supervisados en AWS.
