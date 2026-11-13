# Etapa 5.5-K-W — Caddy real HTTPS + FastAPI K-V, red efímera

**ESTADO: CI APROBADO. SIN DESPLIEGUE EN AWS, SIN HARDWARE Y SIN CAMBIOS EN `main`.**

## Objetivo

Demostrar que un proxy Caddy **real** puede recibir una solicitud HTTPS con certificado válido, sanear las cabeceras no confiables, atestar la solicitud a un FastAPI virtual privado y mantener inaccesibles las rutas del vehículo. Se ejercitó el módulo K-V con SQLite durable e idempotencia K-T; no se utilizó el TestClient para el tramo de red de K-W.

**Prueba de CI aprobada:** [GitHub Actions 43396944609](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43396944609). Registro del paso: `[K-W] Caddy TLS/CA + FastAPI real: 21 comprobaciones OK, SOLO VIRTUAL`.

## Topología ejecutada (solo runner de GitHub Actions)

```text
curl HTTP/1.1, origen simulado de Pages
  └── TLS real (CA efímera validada, hostname 100-30-4-62.nip.io)
       └── Caddy 2.10.2, contenedor con --network host,
           bind 127.0.0.1:9443, sin admin, cap-drop ALL
           + solamente cap NET_BIND_SERVICE
            ├── rutas de admisión virtual aprobadas
            │    └── FastAPI K-V 127.0.0.1:9444 (sin proxy_headers)
            │         └── SQLite privada en RUNNER_TEMP
            └── ruta legacy, movimientos, DEMO, WSS, Swagger → 404
```

- Certificado y CA creados en el runner y eliminados al terminar; `curl` usa `--cacert` y `--resolve`, **sin** `-k`/`--insecure`. El dominio remoto **no se consultó**: la resolución es únicamente local en CI.
- Caddyfile de ensayo: `deploy/staging/kw/Caddyfile.ci`; se valida con `caddy validate` antes de arrancar.
- El contenedor solo dispone de bind mount de los archivos TLS temporales, en solo lectura; el **certificado raíz privado NO se monta** en Caddy. Las claves de prueba y proxy se generan aleatoriamente en cada ejecución, se enmascaran en los logs de Actions y no se suben al repositorio.
- El certificado temporal se transfiere con propiedad de root para evitar añadir `DAC_OVERRIDE` al contenedor al leer las rutas privadas. No elevar capacidades generales.
- El servidor backend solo puede arrancar dentro del runner de GitHub Actions con `APP_ENV=staging`, `ADMISSION_VIRTUAL_ONLY=enabled` y `KW_TEST_LAB=isolated-loopback-only`.
- La cabecera `X-Admission-Client-IP: 8.8.8.8` es una **identidad pública sintética e inmutable EXCLUSIVA de CI**. No se usó el IP real del usuario ni de GitHub. **Es un peligro crítico copiar este Caddyfile como producción:** todas las solicitudes compartirían esa identidad. En un futuro proxy remoto el valor deberá venir del socket real, por ejemplo `{remote_host}`, y se deberá validar la topología de proxies y los límites.
- Se deshabilitó el acceso público al puerto 9444 (bind `127.0.0.1`); Caddy atiende exclusivamente en loopback en el runner. No se abrieron puertos del router o EC2.

## Controles ejecutados a través de Caddy real

1. La API legacy `/`, `/vehiculos/1/movimientos`, DEMO, WSS, Swagger y vehículo ajeno no se exponen en este laboratorio.
2. CORS preflight del origen exacto `https://yori7v7.github.io` responde y un origen ajeno es rechazado.
3. Una solicitud POST requiere las dos claves opacas de idempotencia. Crear devuelve HTTP 201 y repetir **el mismo** par devuelve HTTP 200 con el mismo ticket.
4. El visitante no obtiene `canDrive`, control físico ni API key administrativa.
5. El administrador sin clave recibe 401 y con clave errónea 403; el autorizado obtiene la cola sin secretos de navegador.
6. Supervisión, aprobación virtual temporal, consulta del visitante y revocación completan el ciclo; revocar responde `stop_fisico_confirmado=false`, sin fingir STOP físico.
7. Se enviaron cabeceras falsas `X-Admission-Proxy-Token`, `X-Admission-Client-IP`, `X-Admission-Scheme` y `X-Forwarded-*` desde el supuesto visitante; el proxy las sobrescribió o eliminó, y el backend **solo aceptó** las pruebas de identidad emitidas por Caddy. Esto verifica la transformación en la ruta ensayada, no la resistencia del sistema a todos los ataques de red.

**Hallazgo real:** combinar `header_up -X-Admission-*` con `header_up X-Admission-* valor` hizo desaparecer las pruebas de proxy y el backend respondió correctamente HTTP 403. Se eliminó la operación contradictoria de borrado para esos tres encabezados: Caddy los **sobrescribe directamente**. El resto de cabeceras proxy no confiables sigue eliminándose. Este comportamiento se confirmó con una prueba real, no únicamente con una revisión estática.

## ¿Qué falta para AWS y GitHub Pages?

**NO desplegar este Caddyfile de CI.** El Caddyfile oficial de Windows `deploy/windows/Caddyfile` se conserva igual: atiende `100-30-4-62.nip.io` y envía el tráfico al backend legacy del puerto 8000. Sustituirlo por el archivo aislado K-W rompería CONTROL y MONITOREO, porque en K-W el fallback es HTTP 404. Nunca prometer que el link Pages completo funciona a distancia por este CI.

Requisitos de la siguiente preparación:
- Diseñar un Caddyfile integrado **candidato**, que enrute solo las rutas K-V al servicio virtual y preserve el resto del backend, pero se mantenga sin instalar. Revisar el impacto en los endpoints legacy y las vulnerabilidades administrativas detectadas previamente.
- Sustituir la identidad de CI por `{remote_host}` únicamente con Caddy conectado directamente al cliente; si hay otro proxy/CDN, definir una cadena de confianza explícita sin aceptar `X-Forwarded-For` arbitrario.
- Proteger `127.0.0.1:9444` con ACL y proceso exclusivo, evitar que clientes locales no confiables obtengan la clave del proxy y confirmar la configuración en Windows.
- Preparar el frontend completo de la misma URL Pages, con `guestAdmissionEnabled` y `adminApprovalEnabled` en modo virtual **solo cuando** el endpoint de admisión esté realmente desplegado, accesible desde un teléfono y sin bloquear CONTROL/STOP legacy.
- Antes de acceso físico: autoridad única para Swagger, joystick, DEMO y visitante, watchdog/interlock del ESP, neutralidad mecánica y revocación real bajo prueba supervisada.

**Estado seguro:** GitHub Pages sigue en `https://yori7v7.github.io/control-iot-u4/`, AWS y RDS apagados, batería del carrito desconectada; no hubo POST hacia el vehículo ni cambios en los `main` por K-W.

## Archivos de esta etapa

- `deploy/staging/kw/Caddyfile.ci`: proxy Caddy real **solo CI**, con origen e IP sintéticos.
- `scripts/servidor_55kw_ci.py`: FastAPI virtual solo CI; diagnóstico de estructuras de cabecera cuando hay 401/403, sin imprimir secretos.
- `scripts/prueba_55kw_caddy_ci.py`: verificación HTTPS/CORS/identidad, solicitudes, aprobación, revocación y rutas no existentes.
- `.github/workflows/kw-caddy-virtual-ci.yml`: genera certificados, arranca Caddy Docker/FastAPI en loopback, ejecuta pruebas y destruye los temporales.

**Este documento NO constituye autorización para conectar físicamente la batería ni encender AWS.**
