# Guía técnica de la plataforma 4.3

[Portada y roles](../../README.md) · [Inventario HTTP](apis.md) · [Swagger de producción](https://100-30-4-62.nip.io/docs)

## Persistencia y alcance

El esquema de RDS conserva las seis tablas históricas (`vehiculos`, `comandos`, `estado_vehiculo`, `historial_comandos`, `demos` y `demo_movimientos`). Las doce tablas 4.3 incorporan inventario, capacidades, identidad, titularidad, reservas, tickets, auditoría y DEMOS. La unidad 4.3 conserva el ID legado. Las DEMOS privadas quedan delimitadas por unidad y versión de titularidad, y las DEMOS de fábrica por modelo.

La reserva de invitado es exclusiva durante 120 segundos. La API comprueba su vigencia al operar y el acceso se puede cerrar o revocar. En 4.3 el comprador y el invitado operan dentro de la unidad autorizada. El administrador realiza la gestión comercial desde las rutas de administración.

## Transporte y DEMOS

El navegador inicia una sesión bearer, pide un ticket WSS por conexión y recibe eventos asociados a su unidad. El canal WSS del dispositivo valida una credencial diferente. El endpoint `GET /plataforma/vehiculos/{vehicle}/despacho` informa si hay un enlace de dispositivo disponible para despacho. Por separado, REST confirma aceptación o persistencia y WSS informa eventos observados. La actuación de la unidad 1 se comprobó físicamente. La unidad lógica 4 carece de dispositivo.

El comprador puede iniciar la DEMO programada del servidor y solicitar su cancelación. Para `DEMO_ORIGINAL` (64), FastAPI exige titularidad, enlace de despacho compatible y ausencia de DEMO programada activa. La interrupción física comprobada es CLAXON (128). DETENER (0) libera las salidas del ESP8266 y por sí solo no garantiza interrumpir la secuencia autónoma. La interfaz distingue los indicadores de la API, RDS, WSS del navegador y despacho.

## Verificación local

Ejecuta estos comandos desde la raíz, con Python y un entorno virtual activo.

```powershell
python -m pip install -r requirements-dev.txt
$env:IOT43_MYSQL_TEST = '0'
python -m pytest -q
```

La suite de integración `tests/test_platform43_mysql.py` usa MySQL de laboratorio en `127.0.0.1:33343` y `build/mysql43`. Prepara esa instancia desde PowerShell con los binarios de MySQL 8.4 y un archivo local autorizado que contenga el esquema legado vacío.

```powershell
.\scripts\setup-local43.ps1 -MySqlBin 'RUTA_BIN_MYSQL' -HistoricalSql 'RUTA_ESQUEMA_DE_LABORATORIO'
$env:IOT43_MYSQL_TEST = '1'
python -m pytest -q tests/test_platform43_mysql.py
```

Para la integración del navegador, establece `APP_ENV=development`, `PLATFORM43_ENABLED=true` y `PLATFORM43_DISPATCH=false` en el entorno local. Ejecuta `python -m scripts.local43` en loopback (puerto 8043). El laboratorio valida el directorio de datos de MySQL y deja el despacho inhibido.

La rama de publicación aprobó 359 pruebas de Pytest y 834 subpruebas con MySQL aislado, además de la integración del invitado desde Chrome con despacho inhibido. El inventario de 41 operaciones HTTP se cotejó con el OpenAPI local. La instalación 4.3 y el registro «GO: Instalar verificado» corresponden al reporte del propietario. La identidad binaria del firmware y nuevas pruebas físicas, colaborativas o de migración productiva quedan fuera de la verificación local.
