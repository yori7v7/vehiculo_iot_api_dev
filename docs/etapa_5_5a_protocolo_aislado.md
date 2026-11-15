# Etapa 5.5-A — Primer contrato de dispositivo (aislado, sin AWS)

## Qué implementa este cambio

`app/device_channel/lab54d.py` incluye un **codec de laboratorio** para los marcos
`HELLO54D`, `CMD54D` y `ACK54D` que pasaron la prueba USB en el ESP8266.
Valida HMAC-SHA256, formato estricto, vehículo, identificador de arranque,
generación, secuencia, operación, duración y fases de acuse. `DiagnosticAckFence`
impide atribuir un ACK viejo a una operación nueva y exige leer un HELLO nuevo
antes de continuar tras una respuesta terminal.

**No se incorpora ningún endpoint de dispositivo a `app.main`. No hay ningún
transporte WSS, USB o GPIO asociado a este módulo.** Las rutas reales y el
coordinador de invitados siguen igual que en el merge de 5.2. El modo público
continúa desactivado por defecto y limitado a simulación local.

## Limitaciones de seguridad (obligatorias)

1. Las claves usadas en 5.4-D son **públicas y exclusivamente de prueba**.
   El codec exige recibir dos claves diferentes de 32 bytes; no trae claves
   por defecto. Nunca usarlas en AWS ni como credenciales reales.
2. El HELLO 54D no contiene un desafío aleatorio del servidor ni demuestra
   frescura criptográfica. Una firma HMAC correcta de prueba NO prueba la
   presencia física de un ESP8266 legítimo en un canal de red.
3. El campo `simulado=1` es obligatorio en todos los acuses; un ACK
   `neutral_virtual` no demuestra que el coche esté inmóvil. La propiedad
   `safe_for_physical_relay` permanece siempre en `False`.
4. Los IDs de operación del USB son de 32 bits; los del coordinador de turnos
   de la etapa 5.2 son UUID. Hace falta un mapeo durable y resistente a
   reutilización antes de cualquier despliegue.
5. No se hace arbitraje entre el propietario y los invitados; ambos siguen
   separados. No habilitar un piloto anónimo con la implementación actual.

## Prueba local

Desde la raíz del backend, con `pytest` disponible:

```bash
python -m pytest tests/test_device_channel_lab54d.py -q
```

Las pruebas no abren puertos COM, ni conectan con AWS/RDS, ni transmiten órdenes.
Para comprobar el firmware físico en laboratorio se conserva el proyecto
5.4-D por USB, con batería desconectada y firmware que fuerza salidas a cero.

## Próxima etapa antes de la integración real

- Definir autenticación por dispositivo con credenciales **privadas**, rotables
  y revocables, y desafío/respuesta ligado a cada arranque.
- Crear canal WSS dedicado al dispositivo sin mezclarlo con el WSS de
  MONITOREO y sin permitir que los clientes web se hagan pasar por ESP8266.
- Unificar los despachos administrativo y de invitado en un coordinador único,
  manteniendo parada prioritaria y bloqueos al reiniciar o perder señal.
- Implementar vencimiento local de órdenes en el firmware y ACK autenticado
  correlacionado con la operación del coordinador.
- Definir evidencia verificable de **parada física**, no solo de neutro GPIO;
  ensayar tiempos reales antes de permitir relevos.
- Ejecutar pruebas de banco sin motores y autorizar explícitamente un
  despliegue y pruebas supervisadas posteriores.
