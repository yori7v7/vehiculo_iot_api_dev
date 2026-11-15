# 5.5-J-A — Invitado sin límite fijo bajo supervisión (prototipo local)

**Fecha:** 12/11/2026 (hora de México). **Estado:** implementación de laboratorio empaquetada y **7 tests automatizados locales aprobados**; **prueba con NodeMCU real pendiente**.

## Objetivo de producto

El administrador podrá activar para el profesor un turno de tipo `supervisado` sin cuenta regresiva predefinida, que persiste hasta revocación **solo mientras la supervisión continúe vigente**. El modo temporizado de hasta 30 segundos sigue disponible en el laboratorio 5.5-J-A. Un solo conductor puede enviar movimientos; ambos roles podrían monitorear en la implementación de producto, pero la interfaz pública todavía **no está conectada**.

## Implementación de laboratorio 5.5-J-A

Se preparó un ZIP local que instala **`servidor_55j.py` y `cliente_55j.py` como archivos nuevos**, sin modificar el firmware 5.5-H, las claves privadas, la CA ni el servidor 5.5-I aprobado.

- Operadores de laboratorio autenticados con tokens en la carpeta privada y restringidos a peticiones desde la **misma PC**.
- `cliente_55j.py vigilar` emite un **heartbeat del administrador cada 5 segundos**.
- `cliente_55j.py invitado-supervisado` solicita turno sin fecha final, solo si hubo heartbeat reciente; en estado muestra `modo_turno=supervisado`, `turno_restante_s=null`.
- Si falta la señal administrativa durante **15 segundos**, watchdog en el servidor invalida el permiso del invitado, emite STOP firmado, requiere acuses de neutro **virtual** y solo después vuelve al rol administrador.
- La revocación manual del administrador también envía STOP firmado; órdenes del administrador son rechazadas durante el turno del invitado (HTTP 409).
- Cada movimiento mantiene HMAC, orden/época, duración 100–500ms y STOP posterior; TLS con CA privada permanece verificado.
- Una conexión rota, error de acuses o timeout de despacho cierra y bloquea la sesión.
- Se conservó heartbeat WSS PING/PONG de 5 s.
- Un STOP administrativo durante un movimiento todavía puede quedar serializado tras la orden en vuelo. **No se ha demostrado preempción física urgente.**

## Tests realizados

**7 tests automatizados locales OK**, incluyendo pruebas del contrato WSS firmado, caducidad temporal, rechazo de ACK manipulado, supervisor autenticado, turno indefinido con exclusión, revocación manual, pérdida de heartbeat y STOP automático firmado.

## Restricciones críticas

1. **NO es control remoto real.** El laboratorio opera en la PC del alumno, no en AWS ni en GitHub Pages, y no permite acceso del profesor desde otra laptop.
2. El firmware 5.5-H mantiene GPIO/74HC595 inhibidos y batería desconectada. Los acuses son de neutro virtual, no inmovilidad mecánica.
3. Un proceso automatizado enviando heartbeats **no demuestra presencia física humana**. El producto final deberá definir la supervisión real mediante sesión visible, estado de conexión y control administrativo; no conceder permisos indefinidos por una simple página abandonada.
4. La credencial local `55i-guest.token` es estática y sirve solo para pruebas desde la misma PC: antes de acceso remoto se requieren invitaciones efímeras, rotación y revocación.
5. El prototipo ejecutable se distribuyó por ZIP privado en el chat y **todavía no está integrado en los endpoints de este repositorio**, por lo que se documentan sus alcances para evitar atribuir pruebas no realizadas.
6. El heartbeat y una orden STOP validada no prueban una parada mecánica o el comportamiento bajo corte de alimentación. Falta watchdog local real y prueba supervisada con actuadores.

**No fusionar el PR experimental ni desplegar en producción hasta integrar el coordinador de todos los actores y validar controles físicos.**