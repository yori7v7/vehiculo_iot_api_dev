"""55-K: integracion estructural de roles con WSS virtual."""
import unittest
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class TestKXRoleLink(unittest.TestCase):

    def test_modules_are_valid_python(self):
        for path in (
            "app/public_control/kx_signed_wss.py",
            "app/public_control/kv_kx_virtual_bridge_lab.py",
        ):
            ast.parse(read(path), filename=path)

    def test_guest_revalidated_before_and_after_dispatch(self):
        code = read("app/public_control/kx_signed_wss.py")
        section = code.split(
            "async def execute_virtual(", 1
        )[1].split(
            "async def execute_admin_virtual(", 1
        )[0]

        self.assertIn("ledger.verify_virtual_action(browser_secret)", section)
        self.assertEqual(
            section.count("can_dispatch_virtual_55k("), 2
        )
        self.assertLess(
            section.index("can_dispatch_virtual_55k("),
            section.index("await self._send(code")
        )

    def test_admin_revalidated_before_and_after_dispatch(self):
        code = read("app/public_control/kx_signed_wss.py")
        section = code.split(
            "async def execute_admin_virtual(", 1
        )[1].split("async def stop_virtual(", 1)[0]

        self.assertEqual(
            section.count("can_dispatch_virtual_55k("), 2
        )
        self.assertIn("server_role=ADMIN", section)
        self.assertIn("async with self._lock:", section)
        self.assertLess(
            section.index("can_dispatch_virtual_55k("),
            section.index("await self._send(code")
        )

    def test_admin_identity_verified_by_server(self):
        code = read(
            "app/public_control/kv_kx_virtual_bridge_lab.py"
        )
        route = code.split(
            "@app.post(LOCAL_ADMIN_ACTION", 1
        )[1].split("@app.websocket(", 1)[0]

        self.assertIn(
            "_guard(request, id_vehiculo, admin=True)", route
        )
        self.assertIn(
            "request.headers.getlist(" + '"x-api-key"' + ")", route
        )
        self.assertNotIn("server_role=data.", route)

    def test_original_guest_route_maintained(self):
        code = read(
            "app/public_control/kv_kx_virtual_bridge_lab.py"
        )
        self.assertIn(
            "_guard(request, id_vehiculo, admin=False)", code
        )
        self.assertIn(
            "await authority.execute(ledger, keys[0]", code
        )

    def test_lab_remains_virtual_only(self):
        code = read(
            "app/public_control/kv_kx_virtual_bridge_lab.py"
        )
        self.assertIn(
            '"control_fisico": False', code
        )
        self.assertIn(
            '"canDrive": False', code
        )
        self.assertIn(
            'modo' if False else 'KX_KV_VIRTUAL_BRIDGE_LAB',
            code
        )


if __name__ == "__main__":
    unittest.main()
