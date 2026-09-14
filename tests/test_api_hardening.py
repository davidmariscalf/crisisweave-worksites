import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from worksites import WorksiteStore, build_server


def sample(state="ready", assigned_team=None):
    w = {
        "id": "w-api",
        "title": "Synthetic cleanup",
        "work_type": "debris_removal",
        "state": state,
        "priority": "high",
        "people_needed": 3,
        "skills": ["cleanup"],
        "hazards": ["sharp_debris"],
        "area": "Synthetic District",
        "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
        "source": {"type": "synthetic", "name": "test", "source_id": "s-api"},
    }
    if assigned_team is not None:
        w["assigned_team"] = assigned_team
    return w


class WorksiteApiHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = WorksiteStore(Path(self.tmp.name) / "worksites.db")
        self.store.upsert(sample())
        self.server = build_server(
            self.store,
            "127.0.0.1",
            0,
            token="coord-secret-value",
            allowed_origin="https://field.example.org",
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method, path, *, headers=None, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = Request(self.base + path, method=method, headers=headers or {}, data=data)
        try:
            with urlopen(req, timeout=2) as r:
                return r.status, dict(r.headers), r.read()
        except HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_no_wildcard_cors(self):
        status, headers, _ = self.request("GET", "/api/worksites")
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_exact_origin_preflight(self):
        status, headers, _ = self.request(
            "OPTIONS",
            "/api/worksites",
            headers={
                "Origin": "https://field.example.org",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "https://field.example.org")

    def test_other_origin_preflight_rejected(self):
        status, _, _ = self.request(
            "OPTIONS",
            "/api/worksites",
            headers={"Origin": "https://attacker.invalid", "Access-Control-Request-Headers": "Authorization"},
        )
        self.assertEqual(status, 403)

    def test_write_requires_token(self):
        status, _, _ = self.request("POST", "/api/worksites/w-api/assign", body={"team_id": "team-a"})
        self.assertEqual(status, 401)

    def test_invalid_team_id_rejected(self):
        status, _, _ = self.request(
            "POST",
            "/api/worksites/w-api/assign",
            headers={"Authorization": "Bearer coord-secret-value", "Content-Type": "application/json"},
            body={"team_id": "bad team with spaces"},
        )
        self.assertEqual(status, 409)

    def test_security_headers_present(self):
        status, headers, _ = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")


class ImportAssignmentInvariantTests(unittest.TestCase):
    def test_reimport_cannot_create_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorksiteStore(Path(tmp) / "worksites.db")
            store.upsert(sample())
            incoming = sample("assigned", "partner-team")
            with self.assertRaises(ValueError):
                store.upsert(incoming, "partner-sync")
            current = store.get("w-api")
            self.assertEqual(current["state"], "ready")
            self.assertIsNone(current["assigned_team"])


if __name__ == "__main__":
    unittest.main()
