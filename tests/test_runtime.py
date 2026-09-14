import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

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


if __name__ == "__main__":
    unittest.main()
