# 5.5-K-G — Un único FastAPI ASGI con WebSocket K-C autenticado

**Estado al 12/11/2026 (México):** código preparado en rama experimental y paquete de instalación local entregado en el chat. **37 pruebas de desarrollo aprobadas**, entre ellas WSS con autenticación y ACK HMAC de un dispositivo **virtual**. **NO probado todavía con el ESP8266 físico en K-G**. Los resultados físicos de K-C anteriores se conservan por separado.

## Problema corregido

K-F registraba HTTP `/interno/55kf/*` en `app/main.py`, pero el WSS K-C vivía en `servidor_55kc.py`, **otro proceso**. Por ello no compartían realmente la misma instancia de controlador. Además, K-F aceptaba solo loopback, aunque en el montaje actual la laptop escucha TLS en su IP LAN `192.168.1.82:8443`.

## Cambios en la rama

- `app/public_control/kg_bootstrap.py`: crea la aplicación FastAPI principal con `create_app()`; **bloquea desde el inicio** rutas legacy de movimiento/DEMO poniendo `exclusive_device_control_enabled=True`; incorpora **solo** el `WebSocketRoute` verificado de K-C en el primer lugar de las rutas; crea **un único** `KCController` en `app.state.control = app.state.kf_wss_controller` y ejecuta su watchdog.
- Al autenticar el ESP y recibir su STOP inicial HMAC de neutro virtual, un bootstrap interno llama a `attach_verified_kf_bridge()`: cierre de escrituras legacy, drenaje de requests, `DemoExecutionManager.close_all()` y **otro STOP HMAC autenticado**. Solo después `app.state.kf_bridge` se habilita para consultar/admitir permisos en el **mismo controlador**.
- Si se desconecta el dispositivo, las rutas K-F vuelven a **503**, y las rutas legacy siguen cerradas. Reiniciar FastAPI no reabre el despacho legacy.
- `app/public_control/kf_bridge.py`: admite HTTP operador desde loopback o desde **la IP origen EXACTAMENTE igual a la IP local configurada de la laptop** por K-G. Bloquea a otras laptops, al ESP y las peticiones con proxy u Origin extraño. No se expone CORS a GitHub Pages. La aprobación exige prevalidar supervisor y ticket antes de emitir STOP; el controlador vuelve a comprobar al conceder.
- `scripts/servidor_55kg.py`: lanzador explícito para Windows, desde copia aislada del repo. Carga `servidor_55kc.py` y sus claves privadas *desde la carpeta 55-H de la laptop*, sin incluir esos archivos en GitHub. Configura Uvicorn **workers=1**, TLS LAN en `8443` y ping WSS 5/5.
- `tests/test_kg_bootstrap.py`: smoke tests sobre arranque cerrado, ruta WSS K-C prioritaria, bloqueo de IP externa y rechazo en producción. Un conjunto más amplio de pruebas con el WSS y HMAC real está empaquetado como archivo de prueba de desarrollo.

## Evidencia automatizada

Prueba de desarrollo ejecutada contra FastAPI con simulacro de los endpoints REST del backend y los **mismos controladores/clases K-C** importados desde el paquete local (ESP virtual a nivel de protocolo):

```text
37 passed in 1.47s
```

Se ejecutaron 4 tests del nuevo ASGI unificado, 12 tests de K-F, 8 tests de transición K-E, 5 pruebas legacy y 3 del adaptador DEMO y 5 tests de protocolo K-C (total **37**). Las pruebas confirmaron la secuencia WSS de firma HMAC inicial, segundo STOP durante transición, solicitud en espera, supervisor, aprobación firmada, revocación y denegación al desconectar ESP. No hubo motor ni GPIO físicos en estas pruebas nuevas.

**Precisión:** las pruebas ASGI usaron una factory FastAPI mínima con rutas equivalentes y un gestor DEMO falso. No se ha descargado ni ejecutado toda la API de GitHub en este contenedor, por lo que quedan pendientes pruebas de integración contra el árbol completo en Windows.

## Paquete de Windows

El chat contiene `Etapa_5_5_K_G_ASGI_Unificado_Local.zip`: `INSTALAR_55KG_WINDOWS.ps1`, `cliente_55kg.py`, `LEEME_55KG.txt` y test ASGI de referencia. El instalador verifica que el laboratorio K-C anterior y la plantilla de firmware diagnóstico estén presentes, clona **la rama experimental** en una carpeta nueva bajo Downloads, crea un `.venv` separado e instala `requirements.txt`. Copia el cliente de laboratorio a la carpeta 55-H, **sin sobrescribir private ni firmware**.

La ejecución real en la laptop necesita Git, Python con `py`, conexión a Internet para clonar/instalar, y que el puerto `8443` esté libre. Solo se debe ejecutar **un** servidor entre 55-J, 55-K-C y 55-K-G. Todos los comandos de autorización siguen funcionando **exclusivamente desde la misma laptop**.

## Lo que todavía NO queda resuelto

- No hay HTTPS público AWS ni acceso desde la URL del profesor `https://yori7v7.github.io/control-iot-u4/`; la web oficial permanece intacta. `POST /interno/55kf/accion` continúa dando 403.
- No hay despacho de movimientos desde FastAPI K-F: solo solicitudes, aprobación, consulta, revocación y STOP virtual firmado.
- La coordinación exclusiva utiliza estado local de un solo proceso; no es segura ante múltiples workers, instancias AWS o reinicios sin un fencing persistente.
- La parada no es mecánica ni prioritaria por hardware; hasta 500 ms de orden en vuelo. Se requiere watchdog físico, STOP independiente y verificación supervisada antes de habilitar motores.
- El heartbeat automático de un proceso no verifica presencia humana. La autorización para el examen deberá depender de una supervisión activa comprobable.
- **No iniciar AWS ni RDS** durante esta prueba. El ESP sigue en Wi-Fi de casa; configurar hotspot solo en la recta final, con ensayo integral **antes** del examen.
- Confirmar en el Monitor Serie que el firmware **realmente flasheado** mantiene `ETAPA54_DIAGNOSTICO_SEGURO=1`, porque el script solo lee la plantilla local.

**No fusionar PR, desplegar Internet ni activar motores. Ambas ramas `main` siguen intactas.**
