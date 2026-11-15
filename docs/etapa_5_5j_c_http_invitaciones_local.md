# 5.5-J-C — Vista previa HTTP de invitaciones (laboratorio local)

**Estado a 12/11/2026:** prototipo empaquetado en un ZIP entregado en el chat; **7 pruebas automatizadas HTTP aprobadas localmente**. **NO instalado ni validado todavía en la computadora del alumno**. Ningún cambio en `main`, firmware, AWS/RDS o el sitio GitHub Pages.

## Alcance del ZIP

`Etapa_5_5_J_C_Invitaciones_Local.zip` contiene:

- `invitation_lab.py`: contrato de invitaciones temporales/supervisadas (copia independiente del módulo puro de la rama).
- `invitation_http_lab.py`: API HTTP **aislada del backend principal**, sin router en `app.main`, que ofrece inicio de supervisión, creación/canje de invitaciones de un solo uso, consulta de invitado y revocación.
- `invitation_lab_demo.html`: vista previa de administrador e invitado en dos pestañas de la **misma computadora**, con enlace que porta la invitación en fragmento URL y elimina el fragmento tras leerlo.
- `run_lab.py`: inicia solamente en `127.0.0.1:8766`, con clave administrativa efímera impresa una vez en PowerShell y sin conexiones de hardware.
- `test_lab.py`, `requirements.txt`, `LEEME_55JC.txt`: pruebas y guía de ejecución por terminal.

El anfitrión HTTP **no tiene ningún vínculo con el canal WSS del dispositivo, el coordinador de turnos productivo ni AWS**. Incluso el endpoint de demostración `POST /api/invitado/mover` devuelve 403 siempre. La interfaz muestra un joystick **deshabilitado** por seguridad.

## Características probadas

- Autorización de administrador antes de crear invitaciones; sin heartbeat previo la creación falla.
- Canje atómico una sola vez; sesión de invitado independiente sin API key.
- `supervised`: no tiene caducidad de turno fija; se corta cuando expira el latido administrativo (15 segundos).
- `timed`: duración acotada; expiración verificada.
- Revocación manual invalida invitado y deja `stop_required` activo. Como **no existe ACK de neutral firmado**, una segunda invitación queda bloqueada hasta reiniciar el servidor de demostración.
- HTTP `Cache-Control: no-store`, servidor restringido a loopback, rechazo de acceso remoto/Host externo, no hay comando físico.
- Siete pruebas HTTP de FastAPI TestClient pasaron en el entorno local de desarrollo.

## Limitaciones explícitas

**El enlace generado contiene `127.0.0.1` y funciona solo en la PC que ejecuta el proceso.** No es el enlace final del profesor. No puede controlar motores, ni demostrar STOP físico, ni certificar presencia humana. El programa de heartbeat no constituye vigilancia humana sin políticas adicionales de actividad/visibilidad.

No debe usarse el prototipo de laboratorio como servicio público. **Próximo trabajo:** integrar invitaciones a un único coordinador de turnos y a la sesión WSS del dispositivo con paradas seguras; posteriormente habilitar interfaz de GitHub Pages con credenciales efímeras y validar desde otra laptop, antes de permitir actuadores.