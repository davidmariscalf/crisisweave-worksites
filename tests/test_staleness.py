import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from staleness import stale_report
from worksites import WorksiteStore


class StalenessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = WorksiteStore(Path(self.tmp.name) / "worksites.db")
        self.store.upsert({
            "id": "w1",
            "title": "Requested cleanup",
            "work_type": "debris_removal",
            "state": "requested",
            "priority": "normal",
            "people_needed": 2,
            "skills": [],
            "hazards": [],
            "area": "Test area",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "source": {"type": "synthetic", "name": "test", "source_id": "1"},
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_reports_stale_open_work(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=30)).isoformat().replace("+00:00", "Z")
        with self.store.connect() as con:
            con.execute("UPDATE worksites SET updated_at=? WHERE id='w1'", (old,))
        report = stale_report(self.store, now_value=now)
        self.assertEqual(report["open_worksites"], 1)
        self.assertEqual(report["stale_worksites"], 1)
        self.assertEqual(report["items"][0]["id"], "w1")

    def test_terminal_work_is_not_reported(self):
        now = datetime.now(timezone.utc)
        with self.store.connect() as con:
            con.execute("UPDATE worksites SET state='completed', updated_at=? WHERE id='w1'", ((now - timedelta(days=10)).isoformat().replace("+00:00", "Z"),))
        report = stale_report(self.store, now_value=now)
        self.assertEqual(report["open_worksites"], 0)
        self.assertEqual(report["stale_worksites"], 0)


if __name__ == "__main__":
    unittest.main()
