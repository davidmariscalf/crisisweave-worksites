import unittest

from adapters.crisis_cleanup import convert_record
from worksites import validate_worksite


class CrisisCleanupAdapterTests(unittest.TestCase):
    def sample(self):
        return {
            "id": 123,
            "name": "Private Survivor",
            "address": "123 Private Street",
            "city": "Sample City",
            "county": "Sample County",
            "state": "ST",
            "postal_code": "00000",
            "phone1": "+1-555-0000",
            "email": "private@example.org",
            "location": {"type": "Point", "coordinates": [-77.03653, 38.89767]},
            "flags": [{"is_high_priority": True}],
            "work_types": [{"work_type": "trees", "claimed_by": 42, "status": "open"}],
        }

    def test_converter_removes_direct_pii_and_generalises_location(self):
        out = convert_record(self.sample())
        raw = repr(out)
        self.assertNotIn("Private Survivor", raw)
        self.assertNotIn("123 Private Street", raw)
        self.assertNotIn("+1-555-0000", raw)
        self.assertNotIn("private@example.org", raw)
        self.assertEqual(out["geometry"]["coordinates"], [-77.04, 38.9])
        self.assertEqual(out["location_precision"], "approximate")
        self.assertEqual(out["source"]["type"], "partner_import")
        validate_worksite(out)

    def test_external_claim_does_not_become_crisisweave_assignment(self):
        out = convert_record(self.sample())
        self.assertTrue(out["source"]["upstream_claimed"])
        self.assertEqual(out["state"], "triaged")
        self.assertNotIn("assigned_team", out)

    def test_staffing_is_marked_for_review_not_invented_as_authoritative(self):
        out = convert_record(self.sample())
        self.assertEqual(out["people_needed"], 1)
        self.assertTrue(out["staffing_estimate_required"])
        self.assertTrue(out["integration_review_required"])

    def test_missing_point_location_is_rejected(self):
        row = self.sample()
        row.pop("location")
        with self.assertRaises(ValueError):
            convert_record(row)


if __name__ == "__main__":
    unittest.main()
