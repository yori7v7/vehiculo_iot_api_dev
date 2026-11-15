# 5.5-K-AE — Congelación de superficie HTTP virtual (sin AWS ni ESP)

**Estado:** implementado como contrato de regresión en `tests/test_kae_virtual_surface_freeze.py`, sobre la rama experimental del PR #5. No desplegado. La ejecución definitiva de CI se registra por separado; un archivo de test presente no significa que la prueba haya pasado.

## Riesgo concreto

La propuesta de Caddy desvía ciertas solicitudes desde la URL legacy a un sidecar `127.0.0.1:9444`. Es imprescindible evitar que posteriores cambios agreguen, sin revisión de seguridad, rutas nuevas al sidecar, un upstream público, un origen de identidad controlado por el cliente o envío de `Authorization`/`Cookie` al servicio virtual.

## Dos barreras complementarias

1. **FastAPI virtual:** el test construye `create_kv_virtual_app` solamente en memoria, sin ejecutar el lifespan y sin abrir SQLite/puertos. Congela el conjunto exacto de siete combinaciones de método/ruta: POST solicitud pública; GET estado público; GET bandeja administrativa; POST supervisión, aprobar UUID, rechazar UUID y revocar. Exige la ausencia de Swagger/OpenAPI y rechaza rutas adicionales, incluso si tienen un nombre aparentemente inocuo. El contrato actual es **solo simulación y `canDrive=false`**, no control físico.
2. **Caddy candidato:** se normalizan exclusivamente directivas activas (ignora comentarios) y se comparan con una secuencia fija aprobada. Mantiene el host y upstream legacy `127.0.0.1:8000`, el sidecar local `127.0.0.1:9444`, los tres encabezados de confianza asignados por Caddy, la eliminación de encabezados de cliente peligrosos, la lista acotada de paths y el `handle` de fallback. No se permite ampliación automática de rutas ni sustitución por IPs y cabeceras inyectadas.

La suite introduce **diez mutaciones adversariales sintéticas** en el texto de Caddy y comprueba que la barrera rechaza cada una. Estas mutaciones no se escriben en archivos del repositorio; solo existen como cadenas en memoria.

## Lo que NO prueba

- No verifica una sesión HTTPS desde Internet, reverse proxies desconocidos ni Caddy con certificados reales de EC2.
- No certifica que Caddy de producción tenga el Caddyfile del repositorio, ni que la tarea de Windows entregue correctamente `KW_PROXY_TOKEN`.
- No prueba stop mecánico, ESP8266, GPIO, arbitraje de Swagger/joystick/DEMO ni que la API legacy esté libre de rutas físicas.
- El test de ruta congela el enrutamiento de FastAPI y no constituye una prueba exhaustiva de seguridad de todos los manejadores.
- Las rutas wildcard de Caddy siguen limitadas por el router de FastAPI, pero cambios de Caddy o del framework requerirán otra validación.

## Condiciones antes de la siguiente ventana

Mantener `main` y GitHub Pages intactos, el PR #5 en borrador, EC2/RDS apagados y la batería desconectada. Revisar el resultado de `backend-ci.yml` sobre el SHA exacto. Si la CI falla, corregir sin declarar K-AE aprobada.

**Umbral para solicitar AWS (sin ESP):** una ventana autorizada de inspección read-only de Windows EC2 cuando estén listos el acceso al host, la copia privada restaurable del Caddyfile persistente y la revisión de las tareas actuales. Se utilizará `-Mode Server` de K-AD tras la revisión manual del script. La ESP **no es necesaria** para ese inventario. La ESP y el vehículo solo serán necesarios para ensayos posteriores de WSS físico, neutralidad y STOP/actuadores bajo condiciones seguras.

**Archivos principales:** `tests/test_kae_virtual_surface_freeze.py`, `deploy/staging/kw/Caddyfile.candidate_NOT_DEPLOY`, `app/public_control/kv_virtual_staging.py` y `deploy/staging/kw/kac_ec2_preflight_READONLY.ps1`.
