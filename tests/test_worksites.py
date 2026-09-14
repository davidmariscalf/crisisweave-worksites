import json
import tempfile
import unittest
from pathlib import Path

from worksites import WorksiteStore, validate_worksite


def sample(state="ready"):
    return {
        "id":"w1","title":"Synthetic cleanup","work_type":"debris_removal","state":state,
        "priority":"high","people_needed":3,"skills":["cleanup"],"hazards":["sharp_debris"],
        "area":"Synthetic District","geometry":{"type":"Point","coordinates":[-3.7,40.4]},
        "source":{"type":"synthetic","name":"test","source_id":"s1"}
    }


class WorksiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=Path(self.tmp.name)/"test.db"; self.store=WorksiteStore(self.db)
    def tearDown(self): self.tmp.cleanup()
    def test_validation_rejects_hazard_inference_source(self):
        w=sample(); w["source"]["type"]="hazard_inference"
        with self.assertRaises(ValueError): validate_worksite(w)
    def test_assignment_is_exclusive(self):
        self.store.upsert(sample()); one=self.store.assign("w1","team-a","coord")
        self.assertEqual(one["assigned_team"],"team-a"); self.assertEqual(one["state"],"assigned")
        with self.assertRaises(ValueError): self.store.assign("w1","team-b","coord")
        self.assertEqual(self.store.get("w1")["assigned_team"],"team-a")
    def test_release_and_reassign(self):
        self.store.upsert(sample()); self.store.assign("w1","team-a","coord"); self.store.release("w1","coord"); out=self.store.assign("w1","team-b","coord")
        self.assertEqual(out["assigned_team"],"team-b")
    def test_lifecycle(self):
        w=sample("requested"); self.store.upsert(w); self.store.transition("w1","triaged","coord"); self.store.transition("w1","ready","coord"); self.store.assign("w1","team-a","coord"); self.store.transition("w1","in_progress","lead"); out=self.store.transition("w1","completed","lead")
        self.assertEqual(out["state"],"completed")
    def test_audit_is_append_only_history(self):
        self.store.upsert(sample()); self.store.assign("w1","team-a","coord"); actions=[x["action"] for x in self.store.audit("w1")]
        self.assertEqual(actions,["created","assigned"])

if __name__=="__main__": unittest.main()
