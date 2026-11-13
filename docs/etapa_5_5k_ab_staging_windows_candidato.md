# 5.5-K-AB — Candidato de staging Windows, identidad dedicada y GO/NO-GO

**Estado (13/11/2026): CANDIDATO VALIDADO EN WINDOWS CI, NO DESPLEGADO EN EC2.** No arrancar AWS EC2/RDS, no conectar la batería del carrito y no copiar el material de CI al servidor de producción. El PR #5 sigue siendo trabajo aislado: `main` de backend y frontend se preservan.

## Motivación

K-AA probó que una tarea de Windows ejecutando Python como proceso directo puede alojar K-V en loopback bajo LocalService, y que su detención no interrumpe un servidor sintético en 8000. Sin embargo, **LocalService es una cuenta compartida**, inadecuada como identidad final para un servicio con secretos propios.

K-AB añade un **lanzador candidato de staging** que exige que el manifiesto declare la SID de la identidad que ejecuta la tarea y comprueba que coincide con la identidad real del proceso. Fuera del CI, **prohíbe explícitamente SYSTEM, LocalService y NetworkService**. La cuenta dedicada todavía **NO se ha creado ni aprobado en EC2**.

## Archivos de la etapa

- `app/public_control/kab_windows_staging.py`: ejecutable candidato `python -m app.public_control.kab_windows_staging`; **no instala tareas ni cambia Caddy**. Tiene `--mode preflight` y `--mode serve`. El segundo requiere `enabled=true` en el manifiesto privado; si falta cualquier requisito devuelve NO-GO sin secretos.
- `scripts/kab_ci_direct.py`: puente **exclusivo de GitHub Actions** para ensayar el lanzador con LocalService. No debe copiarse a EC2 ni permitir que una cuenta compartida se convierta en la identidad de staging.
- `tests/kab_windows_staging_ci.ps1`: runner Windows crea una carpeta privada temporal, prueba preflight como LocalService, denegación de `serve` con `enabled=false`, arranque virtual solo tras activación sintética, administración con claves temporales, inexistencia de Swagger/movimientos, parada sin huérfanos, rollback y supervivencia de un servidor dummy en 8000.
- `.github/workflows/kab-windows-staging-ci.yml` y `tests/test_kab_windows_staging_contract.py`: pruebas nativas y de contrato.

## Evidencias automatizadas confirmadas

- [K-AB Windows 43420253430](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43420253430): **23/23 comprobaciones** en Windows Task Scheduler bajo LocalService, incluyendo preflight sin servidor, rechazo de `enabled=false`, arranque local autorizado solo en el fixture de CI, HTTP admin virtual, ausencia de rutas de motores, parada sin huérfanos y rollback sin cortar el dummy legado.
- [Regresión backend 43420259983](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43420259983): **677 pruebas Python + 840 subpruebas aprobadas**; se corrigió el rechazo temprano en Linux antes de importar funciones exclusivas de Windows.
- Los workflows K-W, K-X, K-Y, K-Z y K-AA de la misma revisión se completaron correctamente. Los seis workflows de Windows/Caddy se probaron con identidades y secretos sintéticos, **no con la configuración de EC2**.

**Límite de la evidencia:** la tarea de CI usa LocalService bajo una excepción explícita de laboratorio. La política de K-AB **rechaza LocalService, SYSTEM y NetworkService en staging real**. No se ha creado ni ejecutado todavía una cuenta dedicada en EC2, ni se ha probado ningún Caddyfile integrado allí.

## Diseño protegido: no instalar todavía

Ruta privada candidata para un *futuro* Windows Server: `%ProgramData%\VehiculoIoT-Admission-Staging\`. **No está creada en EC2** y es distinta de `%ProgramData%\VehiculoIoT\`, donde reside la instalación legacy.

Contenido futuro hipotético (no contiene credenciales reales en este repositorio):

```text
%ProgramData%\VehiculoIoT-Admission-Staging\
  staging.json                   [ACL privada, propietario Admin/SYSTEM/cuenta de servicio]
  secrets\
    admin.proof                  [clave distinta, no en git ni en CLI]
    proxy.proof                  [clave distinta, no en git ni en CLI]
  tickets.sqlite3               [creada por el proceso dedicado cuando se active]
  tickets.sqlite3.lock          [exclusividad de proceso y fencing]
```

Esquema de `staging.json`, **ejemplo de estructura sin valores reales**:

```json
{
  "schema_version": 1,
  "mode": "virtual_staging",
  "service_sid": "S-1-5-21-<SID-DE-LA-CUENTA-DEDICADA>",
  "bind_host": "127.0.0.1",
  "bind_port": 9444,
  "database_name": "tickets.sqlite3",
  "enabled": false
}
```

El archivo se mantiene con `enabled: false` salvo decisión explícita de activar el servicio **exclusivamente virtual**. No deben darse permisos de escritura a usuarios comunes ni introducir claves en `staging.json`, línea de comandos, GitHub Pages, `.env` legacy o historial PowerShell. Las credenciales deberían generarse localmente usando fuentes criptográficas del sistema y mantenerse bajo ACL privada, con política de rotación y respaldo definida.

En el futuro, al crear una cuenta dedicada Windows, esta deberá:
- Poder leer el código y ejecutar Python, **sin** escribir sobre código ni dependencias.
- Tener acceso al directorio de staging y archivos de prueba, pero no a `ProgramData\VehiculoIoT`, claves de Caddy, secretos AWS o RDS.
- Crear y modificar exclusivamente su SQLite privada y lock; la comprobación `local_files.check_private` rechazará propietarios o ACE no confiables.
- Escuchar solamente `127.0.0.1:9444` con un solo worker, `proxy_headers=False`, sin OpenAPI/docs y sin endpoints de motores.
- Nunca recibir el poder de modificar las tareas `VehiculoIoT-FastAPI` y `VehiculoIoT-Caddy`.

## Aclaración necesaria sobre el proxy

Caddy actualmente corre dentro de la instalación original y lee su `Caddyfile` **persistente**, no directamente la plantilla de GitHub. K-AB **NO realiza ni valida una recarga de ese Caddyfile en EC2**. Para usar la prueba del proxy en un futuro, Caddy debe recibir el valor del secreto mediante un mecanismo Windows privado revisado, y transmitir la identidad del cliente únicamente desde la conexión confiable.

No basta con que `staging.json` tenga `enabled=true`: también faltan la tercera tarea dedicada, la custodia de secretos, la configuración Caddy integrada, la auditoría de puertos y un rollback ejercitado. El Caddyfile `deploy/staging/kw/Caddyfile.candidate_NOT_DEPLOY` sigue **NO DESPLEGAR**. Nunca usar `deploy/staging/kw/Caddyfile.ci` fuera de GitHub Actions, porque incluye una IP sintética.

**Importante:** el backend K-V mantiene `canDrive=false`. No compartir el puerto 9444 como servicio público ni interpretar autorización virtual como autorización física; la API legacy del puerto 8000 aún existe y requiere protección separada.

## Plan de reversión futuro (no ensayado en EC2)

1. Congelar el commit de staging y documentar el Caddyfile persistente vigente, sus certificados y las tareas originales; mantener una copia privada verificable antes de tocar la configuración.
2. Aislar el sidecar y probarlo **en loopback**, sin Caddy ni Internet, con permisos de la cuenta dedicada. En caso de falla: mantener `enabled=false` y no registrar triggers.
3. Antes de integrar Caddy, validar su candidato y preparar el regreso al Caddyfile persistente original, sin reutilizar el instalador legacy `deploy/windows/install.ps1` (detiene ambas tareas).
4. Solo en una ventana supervisada, integrar el proxy y comprobar que CONTROL/MONITOREO legacy en 8000 siguen accesibles; revertir el enrutamiento si no se cumple la batería de pruebas.
5. Ante cualquier desviación: volver al Caddyfile original validado, detener y deshabilitar **solamente** la tarea de admisión, comprobar 9444 cerrado y 8000 intacto. Conservar evidencias sanitizadas.
6. Conservar RDS y batería apagados durante todas las pruebas virtuales. El control físico exige autoridad única, watchdog, neutralidad y STOP mecánico probado en una sesión posterior.

**Este procedimiento sigue siendo diseño, no una reversión comprobada en EC2.** Antes de habilitar AWS se requiere revisar la topología Windows y la política de cuentas de servicio.

## Próxima etapa

Después de que pase la CI Windows K-AB y las regresiones del backend: preparar el empaquetado y la configuración privada **sin secretos en repositorios**, así como un preflight de EC2 estrictamente de solo lectura. Solo entonces solicitar una ventana de activación virtual de AWS, inicialmente sin RDS ni batería, y finalmente integrar la interfaz pública de Pages.

**Enlace de la entrega digital (sin cambios):** https://yori7v7.github.io/control-iot-u4/
