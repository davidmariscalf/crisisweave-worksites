import sqlite3
import tempfile
import unittest
from pathlib import Path

from audit_guard import install, verify
from worksites import WorksiteStore


def sample():
    return {
        "id": "w-audit",
        "title": "Synthetic cleanup",
        "work_type": "debris_removal",
        "state": "ready",
        "priority": "normal",
        "people_needed": 2,
        "skills": ["cleanup"],
        "hazards": [],
        "area": "Synthetic District",
        "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
        "source": {"type": "synthetic", "name": "test", "source_id": "s-audit"},
    }


class WorksiteAuditGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "worksites.db"
        self.store = WorksiteStore(self.path)
        self.store.upsert(sample())
        install(str(self.path))

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self):
        return sqlite3.connect(self.path)

    def test_append_operations_still_work(self):
        before = verify(str(self.path))["audit_rows"]
        self.store.assign("w-audit", "team-a", "coord-a")
        after = verify(str(self.path))["audit_rows"]
        self.assertEqual(after, before + 1)

    def test_update_is_rejected(self):
        with self.connect() as con:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "audit log is immutable"):
                con.execute("UPDATE audit SET actor='tampered' WHERE seq=(SELECT MIN(seq) FROM audit)")

    def test_delete_is_rejected(self):
        with self.connect() as con:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "audit log is immutable"):
                con.execute("DELETE FROM audit WHERE seq=(SELECT MIN(seq) FROM audit)")

    def test_verify_detects_missing_trigger(self):
        with self.connect() as con:
            con.execute("DROP TRIGGER audit_no_delete")
        with self.assertRaisesRegex(RuntimeError, "missing"):
            verify(str(self.path))


if __name__ == "__main__":
    unittest.main()
