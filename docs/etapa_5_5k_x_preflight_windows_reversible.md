# Etapa 5.5-K-X — Preflight reversible Windows Server, sin tocar AWS

**ESTADO: AUDITORÍA OFFLINE IMPLEMENTADA Y PROBADA. NO DESPLEGADA.** Fecha de corte: viernes 13/11/2026. URL única de entrega digital: https://yori7v7.github.io/control-iot-u4/

## Objetivo y alcance

Preparar la transición futura al servidor Windows EC2 sin sustituir las tareas, archivos, certificados ni procesos originales. La etapa **no** enciende instancias AWS/RDS, modifica reglas de seguridad, instala servicios, edita `.env`, expone `9444`, envía comandos al carrito ni altera el repositorio `main`.

**Evidencia:**
- K-X Windows PowerShell 5.1 real en runner: [GitHub Actions 43399483487](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43399483487): **success**; sintaxis, lectura del contrato y prueba negativa que devuelve NO-GO ante una IP fija falsa.
- K-W Caddy real HTTPS + FastAPI virtual: [GitHub Actions 43399483694](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43399483694): **success**.
- Python regressions: [GitHub Actions 43399377131](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43399377131): **success**; incluyen las barreras del candidato y el preflight.

## Hallazgos sobre la instalación Windows original

Los scripts existentes `deploy/windows/install.ps1`, `run_api.ps1`, `run_caddy.ps1`, `stop.ps1` y `start.ps1` gestionan exclusivamente DOS tareas programadas, bajo SYSTEM:

- `VehiculoIoT-FastAPI`: sirve `app.main:app` con un solo worker y bind `127.0.0.1:8000`. Conserva el backend legacy de CONTROL/MONITOREO.
- `VehiculoIoT-Caddy`: lee el **Caddyfile persistente** en la carpeta privada de ProgramData, NO el archivo de plantilla de GitHub si la instalación ya existe. Administra HTTPS para `100-30-4-62.nip.io` y el upstream 8000.
- El instalador intenta **detener y volver a registrar/reiniciar ambas tareas**. **No ejecutar `install.ps1` ni `restart.ps1` como paso de preparación**: interrumpiría las conexiones WebSocket del proyecto.
- El estado y certificados de Caddy se conservan en una ruta protegida debajo de `ProgramData\VehiculoIoT`. No modificar ACL ni copiar los secretos al repositorio.
- El candidato `deploy/staging/kw/Caddyfile.candidate_NOT_DEPLOY` admite las rutas K-V en `127.0.0.1:9444` y deja el resto de las rutas en `127.0.0.1:8000`, pero **todavía no tiene un proceso sidecar instalado**, una custodia Windows validada para el secreto `KW_PROXY_TOKEN` ni un diseño de rollback ejecutado.

## Auditoría de solo lectura

Archivo: `deploy/staging/kw/kx_readonly_preflight.ps1`.

Cuando llegue el momento adecuado y se haya clonado la rama experimental en un entorno confiable, el modo **Repository** puede ejecutarse sin Windows Server, sin credenciales y sin Internet:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ".\deploy\staging\kw\kx_readonly_preflight.ps1" -Mode Repository
```

El modo **Server** (NO EJECUTAR MIENTRAS AWS ESTÁ APAGADO) únicamente enumera si existen las dos tareas originales, revisa en memoria el Caddyfile persistente y verifica que los listeners 8000 y 9444 sean solamente loopback:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ".\deploy\staging\kw\kx_readonly_preflight.ps1" -Mode Server
```

Cualquier NO-GO produce código de salida `2`. El modo Server no instala, reinicia, habilita ni deshabilita tareas, y no realiza solicitudes de red. No imprime claves, .env, secretos, contenido de certificados ni información de base de datos.

**ATENCIÓN:** el preflight es un chequeo preparatorio, no una auditoría completa de seguridad de Windows ni evidencia de que un servicio público esté activo; podría requerir adaptaciones si la instalación real tiene un Caddyfile personalizado.

## Orden correcto para un FUTURO despliegue supervisado (NO EJECUTAR TODAVÍA)

1. Confirmar evidencia digital de Pages y su repositorio; mantener inmutables los enlaces entregados.
2. Con AWS apagado, congelar el commit experimental y comparar contra `main`. Evaluar dependencias y procesos sin hacer `git pull` sobre el checkout que está ejecutando código en EC2.
3. **Cuando exista una ventana autorizada:** iniciar EC2. Mantener RDS y hardware apagados para pruebas virtuales. Ejecutar SOLO el modo Server de K-X; registrar únicamente los resultados `OK`/`NO-GO` sin compartir secretos.
4. Conservar copia privada del Caddyfile **persistente** y del identificador/revisión de ambos ejecutables y tareas. El archivo de plantilla `deploy/windows/Caddyfile` puede no coincidir con el Caddyfile que realmente ejecuta Windows.
5. Preparar un **tercer proceso separado** para K-V, con una sola instancia, directorio SQLite privado bajo ACL, identidad de proceso aislada, bind exclusivo `127.0.0.1:9444`, modo `staging` y secretos propios de proxy y administrador. No acceder a RDS ni reutilizar la clave administrativa legacy sin un plan de gestión de credenciales.
6. Revisar el Caddyfile candidato con los archivos y las variables de entorno de ese **mismo** servicio Windows. El valor `{remote_host}` sirve para IP real solamente cuando Caddy es el terminador de conexión y no hay proxy/CDN aguas arriba. Definir el límite por IP y la situación IPv6/NAT antes de habilitar visitantes.
7. Validar sintaxis **antes** de cualquier recarga; aplicar una recarga controlada de Caddy, sin tocar FastAPI legacy, exclusivamente si el nuevo servicio virtual responde y se pudo preparar una restauración confiable. No abrir 9444 en Security Groups ni Firewall; no cambiar el puerto 8443 del laboratorio.
8. Desde un teléfono o red externa, probar con el único enlace Pages: solicitud, cola, aprobación y revocación **virtual** y sin claves expuestas. Verificar que los endpoints legacy CONTROL/MONITOREO siguen respondiendo sin desvíos y que los visitantes `canDrive=false`.
9. No habilitar el control físico del visitante hasta pasar las pruebas supervisadas con STOP independiente, exclusión de Swagger/joystick/DEMO y bloqueo de motores sin autorización.

## Plan de reversión — diseño, sin ejecutar

Si la admisión virtual rompe el sitio o no responde:

1. **No conectar batería ni motores.** Cerrar la nueva admisión al público y conservar los registros libres de secretos.
2. Deshacer el único cambio de enrutamiento usando la copia autenticada del **Caddyfile persistente original** (no suponer que la plantilla es idéntica). Validarlo con Caddy antes de recargar.
3. Recargar **solo Caddy** después de verificar que la configuración original es válida; evitar reiniciar la tarea FastAPI/8000, pues hacerlo desconecta WSS/joystick y podría afectar DEMO activa.
4. Verificar los endpoints legacy necesarios a través del dominio original y que el nuevo `9444` no sea accesible externamente. No reutilizar permisos/tickets previos tras reinicio; K-Q revoca por época.
5. Detener/inhabilitar el sidecar K-V y preservar sus evidencias sanitizadas. Mantener `main` y los enlaces de la entrega sin cambios. No descartar la copia original hasta concluir pruebas.

**El procedimiento de rollback NO ha sido ensayado en la EC2 real.** Se requiere ensayo antes de considerar el despliegue aprobado.

## Bloqueos que mantienen AWS en NO-GO

- La API K-V responde **solo con autorización virtual**. La salida `canDrive=false` no habilita motores ni prueba STOP mecánico.
- El Caddyfile candidato no está instalado, no existe todavía una tarea supervisada de K-V en Windows y el almacenamiento/custodia del secreto Caddy `KW_PROXY_TOKEN` no está definido.
- Pueden existir rutas de control legacy en el mismo dominio: el proxy de admisión no las autentica automáticamente. Los controles de visitantes deben estar separados y toda futura autoridad física debe coordinar Swagger, DEMO, WebSocket y joystick.
- Los grupos de seguridad, ACL de Windows, dirección remota real, TLS de producción y almacenamiento durable **no se han verificado** en EC2.
- No se han realizado pruebas externas al laboratorio ni hardware.

**Siguiente trabajo inmediato:** diseñar en rama experimental el arranque supervisado y reversible del sidecar Windows K-V, con identidad aislada y configuración segura. Después de validarlo, autorizar una ventana de prueba AWS virtual sin RDS ni batería.

**Estado general:** la entrega digital de CONTROL y MONITOREO está lista en Pages/repo; K-X es infraestructura preliminar, no despliegue completo.
