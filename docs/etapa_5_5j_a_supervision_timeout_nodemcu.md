# 5.5-J-A — Caducidad automática de turno supervisado observada con ESP8266 conectado

**Fecha:** 12/11/2026 (hora local de Windows), observación del usuario en PowerShell.

## Escenario

En laboratorio, el ESP8266 NodeMCU permaneció conectado al servidor WSS `servidor_55j.py`; el usuario había concedido un turno `guest` de modalidad `supervisado` sin vencimiento fijo. Luego detuvo `cliente_55j.py vigilar` para cesar el heartbeat administrativo de intervalo aproximado 5s, con límite de ausencia de 15s.

## Evidencia del monitoreo (terminal 3)

```text
19:10:05 | operador=guest | supervision=True | TTL=1
19:10:07 | operador=bloqueado | supervision=False | TTL=0
19:10:10 | operador=admin | supervision=False | TTL=0
19:10:12 | operador=admin | supervision=False | TTL=0
19:10:14 | operador=admin | supervision=False | TTL=0
19:10:16 | operador=admin | supervision=False | TTL=0
19:10:19 | operador=admin | supervision=False | TTL=0
19:10:21 | operador=admin | supervision=False | TTL=0
19:10:23 | operador=admin | supervision=False | TTL=0
19:10:25 | operador=admin | supervision=False | TTL=0
19:10:27 | operador=admin | supervision=False | TTL=0
```

**Interpretación limitada:** el sistema dejó de autorizar el turno supervisado al caducar el heartbeat del administrador; mostró transitoriamente `bloqueado` y después `admin`. Esta observación es suficiente para confirmar la transición de estados bajo expiración automática del supervisor **en la sesión de laboratorio con ESP8266 conectado**.

## Sin verificar todavía

- No hay salida aportada de `cliente_55j.py mover --rol guest` **después** de caducar la supervisión; se espera HTTP 409, pero todavía no se observó en esta ejecución.
- No se adjuntaron logs de la terminal del servidor ni del Monitor Serie posteriores al timeout para corroborar por separado el despacho y acuse HMAC de STOP de esta transición.
- No se midió el momento de `Ctrl+C`; las marcas muestran muestreo del estado, **no latencia total desde el cese de supervisión**.
- El servidor no verifica presencia humana; un proceso enviando heartbeat no garantiza vigilancia efectiva.
- GPIO / PC817 / 74HC595 permanecen inhibidos por firmware 5.5-H. Sin batería ni AWS, no se comprobó parada mecánica ni control desde otra computadora.

**Siguiente paso:** probar rechazo de MOVE de invitado tras timeout, consultar estado y revisar logs de STOP; luego continuar integración de seguridad en rama, con pruebas antes del despliegue físico/remoto.
