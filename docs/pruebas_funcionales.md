# Preparación de las tres pruebas funcionales — Thunder Client

Estado: **pendientes de autorización y ejecución**. Este documento prepara
solicitudes y criterios; no acredita que se hayan ejecutado. Durante la etapa 7
no se envían movimientos, DEMO, creaciones, actualizaciones ni eliminaciones
reales. El POST de inicio de DEMO pertenece a la prueba 3; son exactamente tres
pruebas funcionales principales.

## Configuración e identificación de recursos

Iniciar FastAPI localmente con el comando del [README](../README.md). La base
HTTP es `http://localhost:8000`; Swagger está en `/docs` y el monitoreo utiliza
`ws://localhost:8000/ws/vehiculos/{id_vehiculo}`.

Seleccionar los IDs mediante estas consultas públicas, sin crear datos:

| Método y ruta | Datos que se consultan |
| --- | --- |
| GET `/vehiculos` | `id_vehiculo` real y vehículo activo |
| GET `/vehiculos/{id_vehiculo}/comandos` | Comandos del vehículo, sus IDs, códigos y activo |
| GET `/vehiculos/{id_vehiculo}/estado` | Estado inicial y valor conocido de `conectado` |
| GET `/vehiculos/{id_vehiculo}/historial` | Historial anterior, con máximo diez filas |
| GET `/vehiculos/{id_vehiculo}/demos` | `id_demo` real, pertenencia y activo |
| GET `/vehiculos/{id_vehiculo}/demos/{id_demo}/movimientos` | N pasos, orden, comando, código, duración y pausa |

La referencia proporcionada al comenzar la etapa 7 es: 11 comandos del vehículo,
cinco filas de historial y una DEMO activa con seis movimientos. Estos conteos
sirven para cotejar las lecturas; no sustituyen la selección por IDs reales.
La prueba usará los valores que devuelvan los GET, sin modificar la secuencia.

Para los POST de control, configurar un único header en Thunder Client:

```text
X-API-Key: <clave local>
```

Sustituir el marcador sólo en la interfaz local por el valor privado de `.env`.
No poner la clave en la URL, query string o JSON. No guardarla en documentación,
capturas ni colecciones exportadas. En Swagger, **Authorize → LocalApiKey**
representa el mismo header, sin prefijo `Bearer`. Los GET y el WebSocket no
requieren clave.

Con autorización configurada, la falta del header produce 401; un valor
incorrecto, vacío o duplicado produce 403. Si se proporciona un header único
no vacío, una clave de configuración vacía o `change-me`/`changeme` bloquea el
control con 503. No se considera exitosa una prueba que haya recibido uno de
esos errores.

## Prueba 1: movimiento individual

Preparar **POST**:

```text
http://localhost:8000/vehiculos/{id_vehiculo}/movimientos
```

Agregar `X-API-Key` y `Content-Type: application/json`. Plantilla de cuerpo,
todavía no ejecutable hasta sustituir el marcador por un entero real:

```text
{"id_comando": <id_comando_real_del_catalogo>}
```

No enviar nombre, código, origen ni conectado en el cuerpo. El vehículo y el
comando elegidos deben existir, estar activos y corresponderse. Antes de enviar,
guardar las respuestas de estado e historial de ese mismo vehículo.

Cuando se autorice la ejecución, comprobar:

1. HTTP **200**, JSON con `resultado="ok"`, IDs elegidos, comando y código del
   catálogo, `fecha_actualizacion`, `conectado` y `origen="API"`.
2. GET de estado correspondiente al comando solicitado. El POST conserva el
   valor conocido de `conectado`; recibir HTTP no acredita conexión física.
3. Nuevo registro individual API en el historial/RDS. Estado e historial se
   confirman en una sola transacción mediante `sp_actualizar_estado` y
   `sp_registrar_historial`.

Guardar como evidencia la ruta, cuerpo, respuesta y lecturas antes/después,
ocultando el header privado. Si falla el POST, conservar su error y no registrar
una evidencia de éxito. Un fallo previo al commit revierte ambas escrituras.

## Prueba 2: últimos movimientos

Preparar **GET**, sin header privado ni cuerpo:

```text
http://localhost:8000/vehiculos/{id_vehiculo}/historial
```

Cuando se autorice la prueba, comprobar HTTP **200** con una lista de entre cero
y diez elementos. Si hay menos de diez, deben mostrarse sólo los disponibles.
El orden es `fecha_hora DESC, id_historial DESC`; el ID desempata fechas iguales.
El GET no debe modificar estado ni borrar filas antiguas.

Se usa `sp_obtener_historial`. Los orígenes existentes, incluidos WORKBENCH,
MANUAL o API, se conservan: no se filtran etiquetas para ocultar registros.
La ausencia de movimientos DEMO se debe a que su ejecución nunca registra
historial. Guardar el JSON y su número de elementos como evidencia.

## Prueba 3: WebSocket + DEMO sin historial

Preparar una conexión **WebSocket pública** del vehículo y un POST separado:

```text
ws://localhost:8000/ws/vehiculos/{id_vehiculo}
POST http://localhost:8000/vehiculos/{id_vehiculo}/demos/{id_demo}/ejecutar
```

El POST requiere `X-API-Key` y **no lleva cuerpo**. Antes de iniciar la DEMO,
guardar el historial y el GET de sus movimientos. No ejecutar otros movimientos
individuales ni editar catálogos durante esta prueba, para poder comparar las
evidencias antes/después.

Al autorizar la ejecución:

1. Conectar el WebSocket y recibir `estado_actual`, con la fila de estado real
   o `estado=null` si aún no existe. La suscripción no modifica datos.
2. Enviar el POST preparado y comprobar **202**, con `estado="iniciada"`,
   `id_vehiculo` e `id_demo`. El 202 acepta la tarea; no acredita finalización.
3. Recibir `demo_inicio`, después **N** eventos `demo_movimiento` y finalmente
   un único `demo_fin`, todos del mismo vehículo y DEMO.
4. Comparar orden, IDs, comando, código, `duracion_ms` y `pausa_ms` de los eventos
   con el GET previo. La secuencia viene de `sp_obtener_movimientos_demo`.
5. Medir intervalos de recepción con el reloj del cliente: cada paso espera su
   duración y su pausa, **incluida la pausa final**, antes del siguiente evento
   o de `demo_fin`. Admitir el tiempo adicional de procesamiento y transporte.
   Los timestamps de movimientos proceden de MySQL y los de control son UTC;
   no restarlos suponiendo una zona horaria que MySQL no proporcionó.
6. Consultar de nuevo el historial y comprobar que permanece idéntico al
   guardado antes de la DEMO. La ejecución actualiza estado mediante
   `sp_actualizar_estado` y nunca llama `sp_registrar_historial`.

El GET de historial está limitado a diez filas. Si el conjunto real supera ese
límite, el cotejo del total de RDS requiere también una lectura completa mediante
`sp_obtener_historial`; no se borran registros para preparar evidencias.

Guardar los mensajes WebSocket, respuesta 202, configuración N del GET y
comparación del historial. Si aparece `demo_error` o `demo_cancelada`, registrar
ese resultado y no presentarlo como una finalización exitosa de la prueba 3.

## Cancelación y DETENER, si se requieren expresamente

La cancelación es un control disponible, no una cuarta prueba principal ni una
operación automática de la prueba 3. Una DEMO activa se cancela mediante:

```text
POST http://localhost:8000/vehiculos/{id_vehiculo}/demos/{id_demo}/cancelar
X-API-Key: <clave local>
```

No lleva cuerpo. Esperar el **200** con `estado="cancelada"` y el evento
`demo_cancelada` antes de iniciar otra secuencia. La respuesta se emite después
de recoger la tarea y la operación MySQL que estuviera en curso. No se revierten
pasos ya confirmados, ni se inicia un comando supuesto de parada.

Sólo ante una solicitud explícita de DETENER, consultar de nuevo el catálogo
de comandos del vehículo e identificar su `id_comando` real. Después de completar
la cancelación, usar ese ID en el POST normal de movimiento individual de la
prueba 1. **No asumir un ID fijo para DETENER.** Ese POST sí registra un movimiento
individual API; cancelar una DEMO no lo registra.

El WebSocket representa órdenes persistidas y el ESP8266 todavía no se controla
físicamente. Las tres pruebas quedan preparadas; su ejecución real requiere la
confirmación posterior del usuario.
