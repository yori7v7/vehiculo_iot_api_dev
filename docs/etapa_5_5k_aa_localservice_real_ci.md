# Etapa 5.5-K-AA — FastAPI virtual REAL bajo Task Scheduler / LocalService

**ESTADO: LABORATORIO WINDOWS APROBADO. NO DESPLEGADO EN EC2, SIN RDS NI VEHÍCULO.**

**Evidencia definitiva:** [GitHub Actions 43418268476](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43418268476): **24/24 verificaciones aprobadas** en un runner Windows real con Task Scheduler.

## Qué cambió con respecto a K-Y y K-Z

K-Y ejecutó el sidecar virtual con la identidad interactiva del runner y comprobó que no interrumpía un servidor de prueba en 8000. K-Z **registró una tarea ficticia** con LocalService y la desinstaló. K-AA combina ambos ensayos: **el propio Task Scheduler inicia el Python real de K-Y con identidad LocalService**, sirve peticiones HTTP virtuales en `127.0.0.1:9444` y se detiene y desregistra sin cortar el servidor HTTP sintético de 8000.

K-AA NO es una instalación de EC2. El launcher es exclusivamente de CI, exige `KAA_CI_ONLY.marker` y utiliza una configuración privada efímera, sintética. Las tareas reales `VehiculoIoT-FastAPI` y `VehiculoIoT-Caddy` no se modificaron.

## Arquitectura probada

```text
Windows GitHub Actions
  ├── servidor HTTP SINTÉTICO 127.0.0.1:8000, usuario del runner
  └── Task Scheduler: KAA-CI-<aleatorio> (sin triggers)
       └── LOCAL SERVICE / privilegios limitados
            └── python.exe -m scripts.kaa_ci_localservice_direct
                 └── app.public_control.ky_windows_sidecar
                      └── FastAPI K-V, virtual-only, 127.0.0.1:9444
                           └── SQLite privada: propietario/ACL comprobados
```

**El proceso Python es el ejecutable directo de la tarea** (sin un PowerShell padre que deje hijos huérfanos). Al detener Task Scheduler desaparece el listener `9444`; el servicio HTTP sintético de `8000` sigue dando 200.

## Error real de seguridad encontrado y corregido

Los primeros ensayos K-AA fallaron con NO-GO. Task Scheduler registraba la tarea LocalService, pero el sidecar no lograba abrir `9444`. El código `app/public_control/local_files.py` verifica tanto el propietario como TODAS las entradas permitidas de la DACL. En el fixture habíamos concedido una ACE adicional a la identidad individual del runner de GitHub Actions, que **no es de confianza cuando el proceso corre como LocalService**.

La corrección fue alinear los permisos del fixture con la política existente, **no debilitar el validador**:

- Carpeta temporal: propietario grupo Administradores (`S-1-5-32-544`).
- Entradas permitidas: únicamente Administradores, SYSTEM (`S-1-5-18`) y LocalService (`S-1-5-19`).
- ACL sin herencia. No hay permiso individual para el usuario del runner, Everyone, Users ni Authenticated Users.
- La SQLite y el lock son creados por LocalService en esa carpeta aislada. La comprobación real del validador ahora permite iniciar la aplicación.
- Los datos del ensayo, las claves ficticias y el task aleatorio se destruyen al finalizar el workflow.

**Resultado real:** [43418268476](https://github.com/yori7v7/vehiculo_iot_api_dev/actions/runs/43418268476) registra `[K-AA] RESULTADO: 24 comprobaciones con tarea LocalService y sidecar real, SIN EC2.`

## Verificaciones en Windows

- Puerto 9444 inicialmente libre, y backend dummy 8000 disponible.
- Carpeta sin herencia, propietario Administradores, sin ACE extra del runner y sin escritura para usuarios comunes.
- Tarea de nombre aleatorio `KAA-CI-...`, bajo `NT AUTHORITY\LOCAL SERVICE`, sin triggers, no iniciada al registrarse.
- Task Scheduler arranca `app.public_control.ky_windows_sidecar` y la API virtual responde.
- `/docs` y `/vehiculos/1/movimientos` no existen; la solicitud administrativa sin identidad de proxy es rechazada.
- El acceso administrativo del test requiere las cabeceras privadas y una clave ficticia, nunca un token enviado al visitante.
- Al detener la tarea desaparece el listener 9444, no queda proceso Python huérfano, el servidor 8000 sigue respondiendo.
- La tarea se deshabilita y elimina; el dummy 8000 conserva su disponibilidad. No se llamó a AWS ni se modificó Windows EC2.

## Archivos de K-AA

- `scripts/kaa_ci_localservice_direct.py`: ejecuta la aplicación virtual **dentro del propio proceso Python de Task Scheduler**, protegida por fixture CI.
- `tests/kaa_task_localservice_real_ci.ps1`: preparación temporal, identidad LocalService, ACL segura, pruebas HTTP, parada y rollback.
- `tests/test_kaa_localservice_lab_contract.py`: barreras estáticas de CI-only, sin cambios en legacy.
- `.github/workflows/kaa-localservice-sidecar-real-ci.yml`: ejecución Windows GitHub Actions, **sin despliegue**.
- `app/public_control/ky_windows_sidecar.py`: solo añadió diagnóstico opcional de tipo de excepción para K-AA bajo banderas CI, sin registrar mensajes de error ni secretos. Sigue siendo exclusivamente de laboratorio.

Se descartó y eliminó el primer wrapper PowerShell CI porque la tarea podría terminar el padre mientras Python seguía ejecutándose. K-AA usa Python como acción directa para que el proceso registrado sea el propio backend virtual.

## Limitaciones — NO habilitar AWS por K-AA

1. **LocalService no es una cuenta aislada por aplicación.** Otros servicios con la misma identidad podrían acceder a recursos compartidos. Para EC2 debe evaluarse una identidad de servicio dedicada, su ACL específica, los permisos de código de solo lectura, la custodia y rotación de claves.
2. El runner Windows no reproduce las ACL, instalación de Python, Caddy, firewall, Task Scheduler o certificados existentes en la EC2 Windows del usuario. El ensayo confirma viabilidad **en CI**, no compatibilidad automática en ese servidor.
3. El servicio K-V sigue siendo solo virtual. **`canDrive=false`**; el invitado no puede activar motores, Swagger, DEMO ni WSS desde esta API.
4. Falta instalar y auditar un launcher de staging real, con configuración privada en ProgramData, una tercera tarea dedicada y rollback del Caddyfile persistente realmente instalado. El Caddyfile candidato sigue explícitamente **NO DESPLEGAR**.
5. No se ha activado en `main` el flujo de admisión del frontend. La única URL académica continúa siendo **https://yori7v7.github.io/control-iot-u4/**, y su repositorio **https://github.com/yori7v7/control-iot-u4**.
6. Antes de cualquier mando físico se necesitan interlocks, watchdog y STOP mecánico supervisados, además de un árbitro único de joystick, Swagger y DEMO. Las 24 comprobaciones HTTP/Windows no validan neutralidad física.

**Siguiente incremento:** preparar el paquete de lanzamiento de staging Windows de menor privilegio para EC2, con procedimiento de reversión comprobable, antes de autorizar una primera prueba de admisión remota virtual. No usar en EC2 los archivos `kaa_ci_*` ni el marcador de GitHub Actions.
