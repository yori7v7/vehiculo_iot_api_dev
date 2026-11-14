# Plan crítico de entrega — Viernes 13 de noviembre de 2026, 11:00 a. m. CDMX

**Objetivo innegociable:** entregar un ÚNICO enlace de **GitHub Pages**:
`https://yori7v7.github.io/control-iot-u4/`. No reemplazarlo por Swagger, una URL de EC2, túnel o una segunda interfaz.

**Estado de seguridad mientras se prepara:** EC2/RDS apagados, batería RC desconectada, ESP en firmware diagnóstico GPIO/PC817 inhibidos, puerto LAN 8443 sin exposición, ramas `main` intactas. PR experimental backend #5 en borrador.

## Lo que ya está realmente demostrado

1. **Sistema original de la práctica 4.1:** su rama estable `main` contiene interfaz GitHub Pages, joystick 8 direcciones, DEMO y cliente AWS; el usuario reportó pruebas anteriores de mando físico. **Esto no equivale a que el nuevo modo de visitantes tenga autorización física comprobada.**
2. **K-O local:** ensayo manual del alumno por USB, **3/3 barreras HTTP** (12 segundos y 17 lecturas HTTP 200 con ESP conectado, HTTP 503 tras desconectar, HTTP 503 tras reconectar). Solo demuestra cierre de entrada virtual HTTP, no STOP mecánico.
3. **K-Q a K-T:** cierre durable de épocas, solicitudes SQLite con hashes, cuota e idempotencia; pruebas Python y CI aprobadas. Los módulos K-R/K-S/K-T NO están acoplados a la autoridad WSS K-C ni sirven actualmente una API pública.
4. **K-U:** Chrome y FastAPI reales con HTTPS/TLS validado, preflight CORS y un origen simulado de Pages en el runner aislado. Dos E2E HTTPS aprobadas en [GitHub Actions](https://github.com/yori7v7/control-iot-u4/actions/runs/43388515487). **NO se desplegó un sitio accesible desde Internet.**
5. **Frontend experimental:** `guestAdmissionEnabled=false`, `adminApprovalEnabled=false` y barrera `canControl=false` cuando la administración experimental se activa. GitHub Pages estable intacto.

## Decisión de ingeniería

**No pasar directamente al control físico público.** Riesgos concretos:
- El módulo K-S responde solo en ASGI local de pruebas, fuerza identidad loopback y no arranca en `APP_ENV=production`. Abrirlo cambiando banderas rompe su modelo de seguridad.
- El modo de visitantes del frontend puede recibir **aprobación virtual** pero ninguna operación física está arbitrada por K-Q/K-R; Swagger, DEMO y joystick legacy requieren una autoridad única y revocación real.
- El filtro de Chrome **Local Network Access** impide asumir que una página pública llegue sin más a la red privada; no abrir 8443 en el router.
- `HTTP 503` y `STOP HMAC virtual` no demuestran que el circuito RC esté neutralizado cuando se pierden Wi-Fi/WSS, servidor o alimentación parcial.

## Ruta crítica sin microetapas innecesarias

### P0 — Entregable demostrado y plan alternativo, ANTES de editar producción

- Verificar que `main` de frontend/backend está estable; proteger el sitio original de cambios no aprobados.
- Dejar preparada una evidencia académica breve: enlace original, explicación del control ya validado, demos y pruebas local/CI; no afirmar que invitados ya controlan desde Internet.
- Congelar las ramas de experimentos al entrar en fase de despliegue. **NO fusionar PR #5 completo**: mezcla código de diagnóstico local, experimentos y piezas no listas para Internet.

### P1 — API de admisión accesible desde Internet, SIN órdenes al vehículo

- Diseñar un servicio distinto del K-G de laboratorio, con HTTPS público válido, proxy de confianza configurado explícitamente, identidad de visitante de IP confiable, límites reales, persistencia y un único proceso/propietario por archivo o storage transaccional.
- Exponer exclusivamente **solicitudes** y **administración de turno virtual**: jamás rutas de movimiento, DEMO, comando, WSS al ESP o API key al visitante.
- Probar desde un móvil/dispositivo externo, sin privilegios: visitante crea ticket, administrador ve cola y aprueba/revoca en el sitio único, ticket viejo no revive tras reinicio, sin filtración de secreto.
- Una vez probado el servicio remoto **y solo entonces**, preparar la integración de la pantalla completa `index.html` mediante un PR controlado, CSP exacta, CORS, flags seguras y revisión final de `main`.

### P2 — Puente a control físico (NO opcional si la rúbrica exige movimiento visitante)

- Autoridad de movimientos única para **TODAS** las vías: Swagger legacy, mando del administrador, DEMO y visitante. Rechazar mandos simultáneos y estados antiguos mediante epoch/generation durables y control WSS autenticado.
- STOP independiente del navegador y watchdog del ESP con salidas físicas a neutro, integridad de alimentación de PC817/74HC595, demostración de neutralidad física y corte en pérdida de red o servidor.
- Prueba supervisada con batería conectada **solo después** de confirmar el interlock físico con el vehículo inmovilizado. Después prueba de entrega desde móvil externo y rechazo/revocación en tiempo real.

### P3 — Congelación y entrega

- Mantener exclusivamente `https://yori7v7.github.io/control-iot-u4/` como URL pública de entrega.
- Documentar resultados honestamente: `APROBADO`, `VIRTUAL`, `NO VERIFICADO`, `PENDIENTE`. Guardar capturas y logs redactados (sin API keys ni secretos).
- Si no se completan P1/P2 dentro del plazo, preservar `main` funcional y **entregar lo realmente comprobado**, evitando afirmar control de visitantes o seguridad mecánica que no se validó.

## Criterios de alto / go-no-go

- **NO-GO** si la API pública comparte rutas legacy de movimiento sin una autoridad única, si los secretos aparecen en URLs/logs, si no hay protección contra reintentos/reinicio o si el frontend debe omitir la validación TLS.
- **NO-GO físico** si no se verificaron watchdog e interlock mecánico reales, incluso si todas las pruebas CI pasan.
- **GO de admisión virtual únicamente** cuando un tercero puede usar la única URL Pages, crear/revocar solicitudes por HTTPS remoto y constatar `canDrive=false` sin acceso al hardware.
- **GO físico** únicamente después de un ensayo real controlado de pérdida WSS/Wi-Fi, STOP y exclusividad de control, con hardware presente y revocación demostrada.

## Evaluación del estado a la fecha

El desarrollo y las pruebas virtuales tienen gran avance, pero conectar AWS y hardware **no es un cambio mecánico de host**. Las pruebas previas sí aportaron evidencia, detectando fallos reales de desconexión y restricciones de red. A partir de aquí priorizar **despliegue mínimo seguro + demostración de una única URL** antes que añadir nuevas suites de pruebas abstractas.

**Este archivo es una hoja de ruta, NO una certificación de lanzamiento ni un despliegue.**
