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

## Prueba local en Windows PowerShell (recomendada)

1. Descargar la rama `feature/5-5a-dispositivo-protocolo-aislado` del
   backend, no `main`, o actualizar su clon local a esta rama.
2. Desde la **raíz del repositorio**, instalar dependencias:

```powershell
py -m pip install -r requirements-dev.txt
```

3. Ejecutar una sola instrucción desde la raíz:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\prueba_55f_windows.ps1
```

El lanzador genera automáticamente un secreto aleatorio de laboratorio que
hereda el servidor local y el cliente virtual. Inicia Uvicorn en
127.0.0.1:8001, ejecuta la prueba WSS, detiene el servidor y borra la
variable con la clave. Nunca revela la clave ni pide introducir credenciales
de AWS. Puerto 8001 debe estar libre.

La salida esperada del cliente es:

```text
[55-F] Autenticación mutua de dispositivo virtual: OK
[55-F] Orden virtual 9, HMAC y vigencia: OK
[55-F] Orden virtual 0, HMAC y vigencia: OK
[55-F] RESULTADO: WSS BINARIO APROBADO - SIN MOTOR NI AWS
```

La ejecución de PowerShell es una prueba **de laboratorio en la computadora**.
No es un servidor de producción, ni verifica una red remota, ni habilita
movimiento del vehículo.

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
