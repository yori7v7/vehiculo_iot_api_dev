# Etapa 5.5-K-C — Autorización + WSS firmado en un único servidor de laboratorio

**Fecha:** 12/11/2026 (hora de México). **Estado:** paquete ejecutable de laboratorio preparado, **5 pruebas automatizadas de integración aprobadas**, prueba con el NodeMCU físico **PENDIENTE**.

## Objetivo de la etapa

A diferencia de K-B (servidor HTTP de tickets aislado) y J-A (turnos WSS sin navegador), K-C **combina** autorización de visitantes y despacho WSS en un solo proceso Python experimental. La prueba no conecta Azure, AWS, RDS ni GitHub Pages; **no abre acceso al profesor desde otra computadora**.

## Archivos empaquetados

El ZIP privado entregado en el chat se llama `Etapa_5_5_K_C_Coordinador_WSS_Local.zip`. Contiene los archivos nuevos `servidor_55kc.py`, `cliente_55kc.py`, `single_link_admission_lab.py`, `invitation_lab.py`, `INSTALAR_55KC_WINDOWS.ps1`, `LEEME_55KC.txt` y `tests/test_servidor_55kc.py`.

El instalador copia **solo archivos nuevos** junto al servidor 55-J aprobado, sin alterar `servidor_55j.py`, firmware, configuración LAN, CA o claves privadas. Se verifica que la plantilla `firmware/plantilla_55h.ino` contenga `#define ETAPA54_DIAGNOSTICO_SEGURO 1`; esto **no sustituye verificar el firmware realmente cargado en el ESP8266**.

## Flujo integrado

1. Visitante de la misma PC solicita ticket con `POST /55k/solicitud`; hasta la aprobación permanece en `esperando_autorizacion`.
2. Administrador local autenticado con su token existente envía supervisión y selecciona una solicitud concreta (`POST /55k/admin/aprobar`).
3. El mismo controlador bloquea un conductor distinto, envía **STOP firmado** y exige los dos acuses HMAC antes de conceder turno.
4. La orden del invitado exige el secreto opaco asociado a **su navegador aprobado**; se verifica dentro del mismo `asyncio.Lock` que serializa movimientos WSS. El servidor firma orden 68 bytes, verifica acuses y transmite STOP posterior. Todos los GPIO del firmware 55-H siguen forzados a cero.
5. El administrador puede revocar. La sesión invitada se invalida antes de esperar la finalización de un despacho en curso y un STOP firmado devuelve el turno lógico al administrador.
6. Si faltan latidos del supervisor o el ESP se desconecta/rechaza un acuse, se rechazan nuevas órdenes y se cierra sesión de forma conservadora.

**No se exponen las rutas antiguas `/55i/accion/*` y `/55i/turno` en el servidor K-C**; solo se utiliza el nuevo proceso K-C en puerto 8443, nunca a la vez que 55-J.

## Evidencia de desarrollo

Pruebas automáticas `tests/test_servidor_55kc.py`, `TestClient` de FastAPI con **ESP virtual a nivel de protocolo WSS**, challenge/response HMAC, órdenes firmadas, secuencias y acuses virtuales firmados:

- Rechazo sin aprobación, falta de autenticación y ausencia de rutas de movimiento legacy: OK.
- Denegación de cliente LAN ajeno a la PC y secreto navegador inválido: OK.
- Ciclo completo solicitud→aprobación→WSS→orden diagonal 9→STOP→revocación→comando admin: OK.
- Caducidad automática de supervisión y STOP HMAC de cierre: OK.
- Acuse HMAC manipulado cierra canal e invalida invitado: OK.

**Resultado: 5 passed (1.08 s)** en el contenedor de desarrollo. No se ejecutaron todavía con el ESP físico tras este cambio.

## Lo que NO demuestra

- **No integra el backend AWS ni sus endpoints REST/Swagger existentes**. Los comandos de AWS siguen siendo un camino independiente y requieren cerrarse/unificarse antes de autorizar movimientos físicos remotos.
- **No habilita la URL oficial GitHub Pages** para pedir control. Los operadores HTTP aún están limitados a la **misma laptop** y el ESP usa WSS LAN. El profesor empleará en el examen exclusivamente `https://yori7v7.github.io/control-iot-u4/` cuando esté lista la integración.
- **NO es STOP físicamente prioritario**: el controlador serializa órdenes y un STOP puede quedar detrás de una orden en vuelo de máximo 500ms, además de latencias de transporte/acuse. El watchdog físico, evidencia mecánica de neutro y prueba con motores son pendientes.
- Los acuses `neutral_reportado_no_fisico` demuestran protocolo, no detención mecánica. Dejar batería desconectada.
- Los permisos se guardan en memoria de un solo proceso y no están diseñados para multiworker, alta disponibilidad, redes externas ni autenticación pública de producción.

## Próximo paso

El alumno debe instalar el ZIP en Windows junto al laboratorio 55-H/55-J, iniciar **solo `servidor_55kc.py`** en la terminal 1, `cliente_55kc.py vigilar` en la terminal 2, y solicitudes/aprobaciones/comandos en la terminal 3. Consultar la guía del ZIP y conservar los logs **sin tokens privados**. Si pasa, continuar hacia unificar el backend AWS en rama, integrar la interfaz oficial sin añadir páginas, validar desde laptop del profesor y preparar el hotspot al final, pero **antes del examen**.

**Estado Git:** rama experimental y PR borrador, `main` no alterada. No desplegar al vehículo real ni a Internet.
