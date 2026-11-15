# 5.5-K-F — Puerta FastAPI hacia el mismo controlador K-C (inactiva por defecto)

**Fecha:** 12/11/2026. **Estado:** código integrado en la rama experimental del backend; **28 pruebas ASGI/seguridad aprobadas en laboratorio** (12 K-F y 16 de regresión K-D/K-E). No instalado en la PC del usuario ni en AWS.

## Cambio real realizado

- **`app/public_control/kf_bridge.py`** contiene rutas **internas** `/interno/55kf/*`, ocultas del esquema Swagger y restringidas a loopback, sin CORS externo:
  - `POST /solicitud` crea una solicitud de visitante.
  - `GET /solicitud/estado` devuelve espera, autorización o revocación (sin filtrar el token de turno interno).
  - `GET /admin/pendientes`, `POST /admin/supervision`, `/admin/aprobar`, `/admin/rechazar`, `/admin/detener` usan el token administrativo de laboratorio y **delegan en la misma instancia** de `KCController`.
  - `POST /accion` rechaza siempre con **HTTP 403**; NO despacha motores desde FastAPI.
- **`app/public_control/kf_attach.py`** exige una instalación explícita por código Python de confianza. Debe coincidir por identidad `app.state.kf_wss_controller is controller`, verificar que el ESP esté autenticado y que la app opere en `development` sin simuladores competidores.
- La instalación ejecuta la barrera de transferencia K-E: cierra escrituras legacy, drena solicitudes, recoge DEMO y exige un callback que solicita STOP al **propio** controlador WSS y recibe confirmación lógica firmada. Solo entonces crea `app.state.kf_bridge` y conserva los comandos heredados bloqueados.
- **`app/main.py`** registra el router y crea `kf_bridge=None` y `kf_wss_controller=None`. Por ello, **el estado inicial siempre es 503**. Ni AWS, ni Swagger ni el frontend pueden activarlo mediante un endpoint.
- **`tests/test_kf_bridge.py`** añade 12 pruebas nuevas con controlador WSS simulado, más 16 pruebas de K-D/K-E que pasaron en la misma corrida.

## Resultado exacto de la batería local

```text
28 passed in 0.53s
```

Se verificaron: inicio bloqueado, vinculación por identidad de un mismo controlador, orden de STOP lógico y cierre de DEMO, espera/aprobación/revocación, ausencia de movimiento desde la API, clave admin separada de secreto navegador, denegación de origen público y proxy, modo producción bloqueado, rechazo al desconectarse el ESP, fallo seguro ante STOP y compatibilidad con K-D/K-E.

**Las pruebas usan un KCController falso para simular los callbacks; NO son una prueba adicional contra el ESP físico.** Las 5 pruebas de protocolo K-C y la ejecución manual previa con NodeMCU se registran por separado.

## Limitaciones y condiciones de arranque

Esta etapa **no monta aún el WebSocket K-C dentro del proceso FastAPI principal**, porque el K-C verificado vive en el servidor local independiente `servidor_55kc.py`. El módulo `kf_attach` acepta su instancia mediante una instalación interna, pero todavía no existe el lanzador que levante ambos en el mismo ASGI y ejecute esa instalación.

Para el siguiente hito deben cumplirse, sin saltos:

1. **Un único Uvicorn worker**: arrancar la app FastAPI y el endpoint WSS K-C en el **mismo proceso y bucle**, no en dos servidores `8443` competidores. Hacer que el WebSocket K-C almacene su **única** instancia de controlador en `app.state.kf_wss_controller`.
2. Cerrar desde el arranque las rutas legacy de movimiento/DEMO; solo tras autenticación del ESP, drenaje y STOP lógico firmado ejecutar `attach_verified_kf_bridge`.
3. Comprobar que desconectar/reiniciar ESP invalida sesiones, que la caída/reinicio de Uvicorn no reabre permisos y que una DEMO empezada antes no continúa.
4. **No exponer esta API local a Internet**: los endpoints existentes de K-F son solo para validar el acoplamiento. La URL oficial `https://yori7v7.github.io/control-iot-u4/` no los consume todavía.
5. Construir por separado el diseño de autorización HTTPS pública, estado durable/leases/épocas tras reinicio y las restricciones de CORS, rate limits, antifraude y supervisión humana.
6. Antes de motores, añadir watchdog de dispositivo, prioridad STOP, evidencia de neutro eléctrico/mecánico y pruebas supervisadas. Un ACK `neutral_reportado_no_fisico` solo demuestra protocolo.

**No activar por defecto, no copiar API key a frontend, no desplegar a AWS todavía.** Ambas ramas `main` se mantienen intactas. El hotspot del teléfono se configurará y comprobará en la fase final **antes** del examen, no durante él.
