"""Cliente de laboratorio: ejercita WSS sin GPIO, sin Arduino y sin AWS.

Uso: python -m scripts.prueba_wss_55f
Requiere el DEVICE_LAB_KEY local (aleatorio y privado; NO subir a Git).
"""
from __future__ import annotations

import hmac
from hashlib import sha256
import json
import os
import time

from websockets.sync.client import connect

from app.device_channel.authenticated_lab import (
    DeviceSession, TX_CONTEXT, RX_CONTEXT, decoded, encoded,
    device_auth_reply, verify_server_auth,
)
from app.device_channel.command_wire import CommandWire, DeviceAck


def main() -> None:
    key = decoded(os.environ.get("DEVICE_LAB_KEY"), 32)
    url = "ws://127.0.0.1:8001/ws/dispositivos-lab/1/contrato"
    print("[55-F] Dispositivo virtual WSS local; NO hay movimiento físico.")
    with connect(url, open_timeout=3, close_timeout=3, max_size=512) as ws:
        challenge = json.loads(ws.recv(timeout=4))
        boot, device_nonce = os.urandom(16), os.urandom(16)
        reply = device_auth_reply(key, challenge, boot=boot, nonce_device=device_nonce)
        ws.send(json.dumps(reply))
        confirmation = json.loads(ws.recv(timeout=4))
        rx_key = verify_server_auth(key, challenge, reply, confirmation)
        binding = (int(challenge["vehiculo"]).to_bytes(4, "big") +
                   decoded(challenge["desafio"], 32) +
                   boot + device_nonce + decoded(confirmation["sesion"], 16))
        tx_key = hmac.new(key, TX_CONTEXT + binding, sha256).digest()
        assert hmac.compare_digest(rx_key, hmac.new(key, RX_CONTEXT + binding, sha256).digest())
        session = DeviceSession(
            1, confirmation["sesion"], encoded(boot), encoded(device_nonce),
            tx_key, rx_key, binding,
        )
        wire = CommandWire(session)
        print("[55-F] Autenticación mutua de dispositivo virtual: OK")

        for expected_code in (9, 0):
            frame = json.loads(ws.recv(timeout=4))
            order = wire.verify_order(frame, now_ms=int(time.time() * 1000))
            if order.code != expected_code:
                raise RuntimeError("Se recibió un comando inesperado.")
            print(f"[55-F] Orden virtual {order.code}, HMAC y vigencia: OK")
            for phase, neutral in ((1, False), (2, True)):
                if phase == 2 and order.duration_ms:
                    time.sleep(order.duration_ms / 1000)
                ack = DeviceAck(
                    order.vehicle_id, order.session_id, order.operation_id,
                    order.generation, order.epoch, order.sequence,
                    int(time.time() * 1000), phase, neutral,
                )
                ws.send(json.dumps(wire.sign_ack(ack)))
        done = json.loads(ws.recv(timeout=4))
        if done.get("tipo") != "prueba_contrato_terminada" or done.get("parada_fisica_verificada") is not False:
            raise RuntimeError("El servidor no confirmó el cierre virtual esperado.")
        print("[55-F] RESULTADO: WSS BINARIO APROBADO - SIN MOTOR NI AWS")


if __name__ == "__main__":
    main()
