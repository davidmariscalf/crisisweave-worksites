import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from worksites import WorksiteStore
from worksites_server import build_hardened_server


class RuntimeTests(unittest.TestCase):
    def test_hardened_server_uses_worker_ceiling_and_health_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorksiteStore(Path(tmp) / "worksites.db")
            server = build_hardened_server(
                store,
                "127.0.0.1",
                0,
                max_workers=7,
                socket_timeout=3,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertEqual(server.max_workers, 7)
                self.assertEqual(server.socket_timeout, 3.0)
                with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/health", timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(b'"ok":true', response.read().replace(b" ", b""))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_configured_token_protects_all_operational_reads_but_not_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorksiteStore(Path(tmp) / "worksites.db")
            server = build_hardened_server(store, "127.0.0.1", 0, token="secret-test-token")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urlopen(base + "/api/health", timeout=2) as response:
                    self.assertEqual(response.status, 200)
                with self.assertRaises(HTTPError) as denied:
                    urlopen(base + "/api/worksites", timeout=2)
                self.assertEqual(denied.exception.code, 401)
                request = Request(
                    base + "/api/worksites",
                    headers={"Authorization": "Bearer secret-test-token"},
                )
                with urlopen(request, timeout=2) as response:
                    self.assertEqual(response.status, 200)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_no_token_mode_remains_available_for_local_synthetic_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorksiteStore(Path(tmp) / "worksites.db")
            server = build_hardened_server(store, "127.0.0.1", 0, token=None)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/worksites", timeout=2) as response:
                    self.assertEqual(response.status, 200)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
