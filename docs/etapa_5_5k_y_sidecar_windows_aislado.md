# Etapa 5.5-K-Y — sidecar de admisión virtual Windows, aislado del CONTROL legacy

**Estado:** código de laboratorio implementado en rama `feature/5-5a-dispositivo-protocolo-aislado`; no desplegado en EC2. El sidecar es **estrictamente virtual**: `canDrive=false`, sin motores, WSS, Arduino, DEMO, RDS ni conexión a servicios AWS. GitHub Pages y `main` permanecen intactos.

## Objetivo

Preparar un tercer proceso Windows para solicitudes del profesor que pueda iniciarse, detenerse y reiniciarse **independientemente** de las tareas originales `VehiculoIoT-FastAPI` y `VehiculoIoT-Caddy`. El objetivo final conserva el único enlace de entrega `https://yori7v7.github.io/control-iot-u4/`.

Este incremento NO registra la tercera tarea, ni modifica ProgramData, ni instala la configuración candidata Caddy en la EC2. **No ejecutar K-Y manualmente en el servidor real**: el lanzador se niega a funcionar fuera de Windows GitHub Actions.

## Implementación de laboratorio

- `app/public_control/ky_windows_sidecar.py`: ejecuta `create_kv_virtual_app` directamente con Uvicorn sobre **127.0.0.1:9444**, `workers=1`, `reload=False`, `proxy_headers=False` y sin access logs. El script exige `GITHUB_ACTIONS=true`, `KY_WINDOWS_CI_ONLY=isolated-sidecar`, `APP_ENV=staging` y `ADMISSION_VIRTUAL_ONLY=enabled`.
- Los parámetros secretos provienen de **un archivo JSON privado temporal** bajo `RUNNER_TEMP`, nunca de línea de comandos, del frontend, de `.env` legacy o del repositorio. Validaciones: contrato de esquema exacto, puerto/host fijos, ruta fuera de repositorio y dentro de runner, tamaño máximo, secretos distintos de longitud apropiada y archivo no simbólico. El test Windows establece ACL restringidas al usuario del runner, SYSTEM y Administradores. Todo se destruye al concluir.
- `tests/ky_windows_sidecar_ci.ps1`: Windows PowerShell 5.1 inicia en **8000** un servidor HTTP sintético como sustituto del backend legacy, y en **9444** el sidecar virtual real. Comprueba denegación sin bandera CI, rechazo al host 0.0.0.0, bloqueo de rutas de movimientos/Swagger, identidad de proxy requerida, clave administrativa separada, arranque/parada/reinicio propio del sidecar y persistencia de la disponibilidad del 8000.
- `tests/test_ky_windows_sidecar_contract.py`: controles estáticos para impedir importación automática de K-Y en `app.main`, `run_api.ps1`, `run_caddy.ps1`, `install.ps1` o `Caddyfile`; el backend original conserva `127.0.0.1:8000`.
- `.github/workflows/ky-windows-sidecar-ci.yml`: Windows runner real, Python 3.12, pruebas end-to-end por HTTP loopback y limpieza completa. **No simula el sidecar**, pero sí usa un sustituto básico para el servicio legado de 8000. Por ello no certifica el frontend real ni EC2.

## Barreras de producción

**NO-GO** hasta cumplir, al menos:

1. Definir e implementar una identidad Windows y una tercera tarea dedicada sin alterar las dos tareas originales y sin elevar permisos sobre `app.main`; probar duplicación de procesos, recuperación y política de reinicio.
2. Custodiar el archivo de secretos y el SQLite de K-V en ProgramData con ACL comprobadas, rotación de secretos, backups y owner de proceso único. El JSON de CI es **solo demostrativo** y no debe reutilizarse.
3. Crear y probar la configuración de Caddy integrada con las rutas de admisión virtual y el upstream original 8000; nunca copiar `deploy/staging/kw/Caddyfile.ci` a AWS.
4. Ensayar en Windows los fallos y rollback: sidecar caído, SQLite bloqueada, Caddy inválido, reinicio de EC2 y reanudación de la API legacy intacta.
5. Probar desde un celular externo la misma URL de GitHub Pages (con la vista completa integrada, que todavía no está habilitada). Separar totalmente el permiso virtual de cualquier ruta física.
6. Antes de las pruebas físicas del miércoles: comprobar watchdog/interlock, STOP mecánico y un árbitro único para Swagger, joystick, DEMO y visitante. La prueba HTTP de K-Y **no demuestra seguridad de motores**.

## Enlaces y estado

- Solo la rama experimental del backend recibió K-Y; PR #5 sigue en borrador.
- Frontend `main`, GitHub Pages, API EC2, RDS, llaves AWS, y firmware del vehículo no fueron modificados.
- El enlace definitivo de entrega digital sigue siendo `https://yori7v7.github.io/control-iot-u4/` y el repositorio `https://github.com/yori7v7/control-iot-u4`.
- Evidencia de la primera prueba de 14 comprobaciones Windows: [GitHub Actions 43401328770](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43401328770), **success**. Se agregó una verificación adicional de reinicio y exclusiva SQLite para la prueba definitiva, que debe comprobarse por separado.

**Siguiente decisión:** primero verificar el ensayo definitivo de Windows; después diseñar la tercera tarea con un procedimiento de instalación y reversión independiente, sin encender AWS por adelantado.
