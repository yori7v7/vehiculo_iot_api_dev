"""K-AC: servicio legacy SINTÉTICO para probar coexistencia y reversión.

No importa FastAPI original, WS, RDS, ESP, ni rutas de movimiento.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json


class LegacyStub(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/__kac_legacy_probe":
            data = json.dumps({"legacy": True, "control_fisico": False}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    def log_message(self, *_):
        return


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8000), LegacyStub).serve_forever()
