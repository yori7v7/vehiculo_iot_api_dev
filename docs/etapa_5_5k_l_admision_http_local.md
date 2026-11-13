# Etapa 5.5-K-L — Admisión HTTPS local en el mismo ASGI (NO PRODUCCIÓN)

**Estado:** implementado solo en `feature/5-5a-dispositivo-protocolo-aislado`. No se habilitó el frontend oficial ni se modificaron `main`, AWS o firmware. Batería desconectada, PC817 inhibidos en pruebas.

## Objetivo

Conectar el contrato HTTPS de visitante `/publico/vehiculos/1/solicitudes` (K-I) con el mismo `KCController` autenticado por WSS que utiliza K-K para supervisar, aprobar, rechazar y revocar. No crear una segunda cola ni un segundo despachador. La URL oficial del profesor permanece `https://yori7v7.github.io/control-iot-u4/` y el profesor no necesita contraseña, pero **la URL pública todavía NO accede a este laboratorio privado**.

## Implementación

- `app/public_control/kg_bootstrap.py`: `ki_contract_test_enabled=False`, `ki_ingress=None` al crear K-G. Después de ESP autenticado + STOP virtual HMAC + handover legacy a `exclusive`, instala `GuestIngressLab(controller)`, reutiliza `kf_wss_controller` y habilita K-I y K-K. Si el ESP pierde conexión o K-G se cierra, ambos flags se desactivan. No existe API para activar la ruta desde fuera.
- `app/public_control/ki_ingress.py`: cuando `kg_lab_mode=True`, solo acepta conexiones cuyo origen TCP sea loopback o la IP exacta de la laptop configurada. Bloquea LAN remota, X-Forwarded-Host, proxy headers, Host/Origin incorrectos, cookies y credenciales de administrador en solicitudes de visitante. Mantiene el filtrado de `guest_token` y no incluye rutas de movimiento.
- `tests/test_kl_guest_lab.py`: 4 pruebas integradas con `ScopedControlMiddleware` real y controlador virtual compartido. Verifican identidad única, solicitud/estado/cola/aprobación 120 s/revocación, cierre ante desconexión, rechazo de otras IP LAN y cierre antes del handover.
- `scripts/prueba_55kl_admision_local.py`: ensayo manual en la laptop que usa el módulo `prueba_55kk_post_virtual_seguro.py` descargado previamente por el usuario para reutilizar CA pública, comprobación de IP local, TLS estricto y verificación del firmware de diagnóstico. No inicia movimientos y nunca imprime la API key o `browser_secret`.

## Evidencia

**GitHub Actions**: commit que añade los 4 tests integrados `9c60c9a6a74ee20e0c0873a6463157c1a4b6e328`, ejecución [43371888666](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43371888666): **606 tests y 840 subtests aprobados**. Las siguientes confirmaciones de CI de los scripts y la documentación deben registrarse por separado.

**PENDIENTE**: ejecutar el guion K-L en la laptop con ESP WSS real, TLS validado, en modo virtual, y aportar la salida. Ningún resultado anterior valida por sí mismo el nuevo montaje real K-L.

## Límites críticos

- La ruta K-I de laboratorio **NO** es admisión pública desde Internet. Solo desde la propia laptop en `192.168.1.82:8443`; nunca abrir puertos en router ni desplegar directamente en AWS.
- Sin persistencia transaccional durable ni fencing de épocas entre workers/reinicios, y sin rate limit real por IP o identidad, no apta para tráfico público.
- La prueba de STOP HMAC confirma solo neutro virtual, **NO** parada mecánica ni control de motores. Faltan prioridad preemptiva, watchdog real, neutralidad verificada, unificación de Swagger/DEMO/joystick y pruebas físicas.
- El heartbeat cada cinco segundos no acredita presencia humana. Se requerirá una política fail-closed ante pestaña oculta, caída de red y ausencia del supervisor.
- `guestAdmissionEnabled=false` y `adminApprovalEnabled=false` en la rama experimental del frontend. **No activarlos ni hacer merge** hasta la infraestructura pública segura.

## Procedimiento de prueba en Windows

Con la batería desconectada y el ESP en modo diagnóstico realmente grabado:
1. En Terminal 1, detener K-G anterior con Ctrl+C, ir a `$HOME\Downloads\Etapa_5_5_K_K_Backend_Experimental`, actualizar la rama con `git pull --ff-only` y reiniciar `& ".\.venv\Scripts\python.exe" ".\scripts\servidor_55kg.py"`.
2. En Terminal 2, Monitor Serie Arduino a la velocidad definida por `Serial.begin(...)`; el arranque de ROM puede imprimir a 74880 baudios. Esperar autenticación WSS y STOP virtual HMAC en Terminal 1.
3. En Terminal 3, con `prueba_55kk_post_virtual_seguro.py` en Descargas, ejecutar `& "$HOME\Downloads\Etapa_5_5_K_K_Backend_Experimental\.venv\Scripts\python.exe" "$HOME\Downloads\Etapa_5_5_K_K_Backend_Experimental\scripts\prueba_55kl_admision_local.py" --ip 192.168.1.82 --puerto 8443 --confirmar-simulacion`. La clave administrativa se solicita de forma oculta.
4. Si la revocación de contingencia no se confirma, mantener apagados los actuadores y diagnosticar con K-G cerrado antes de cualquier otra prueba.

**Prohibido encender AWS/RDS, activar movimientos, exponer el puerto 8443 o modificar `main` en esta etapa.**
