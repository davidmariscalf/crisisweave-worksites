import unittest

from public_export import public_worksite


class PublicExportTests(unittest.TestCase):
    def test_real_worksite_is_minimised_and_generalised(self):
        row = {
            "id":"w1","title":"Cleanup","work_type":"debris_removal","state":"assigned","priority":"high",
            "people_needed":4,"skills":["cleanup"],"hazards":["sharp_debris"],"area":"Sample City",
            "geometry":{"type":"Point","coordinates":[-77.03653,38.89767]},
            "source":{"type":"partner_import","name":"Partner","source_id":"123","url":"https://private.example/item/123","token_hint":"secretish"},
            "assigned_team":"team-private","coordinator_instructions":"Go to exact side entrance",
            "description":"Free form operational text","created_at":"2026-01-01T00:00:00Z","version":3,
        }
        out = public_worksite(row)
        self.assertEqual(out["geometry"]["coordinates"],[-77.04,38.9])
        self.assertEqual(out["location_precision"],"approximate")
        self.assertEqual(out["visibility"],"public")
        self.assertNotIn("assigned_team",out)
        self.assertNotIn("coordinator_instructions",out)
        self.assertNotIn("description",out)
        self.assertNotIn("url",out["source"])
        self.assertNotIn("token_hint",out["source"])

    def test_synthetic_demo_can_preserve_exact_point(self):
        row = {
            "id":"w1","title":"Demo","work_type":"assessment","state":"ready","priority":"normal",
            "people_needed":1,"skills":[],"hazards":[],"area":"Synthetic",
            "geometry":{"type":"Point","coordinates":[-3.70379,40.41678]},
            "source":{"type":"synthetic","name":"Demo","source_id":"s1"},
        }
        out = public_worksite(row)
        self.assertEqual(out["geometry"],row["geometry"])
        self.assertEqual(out["location_precision"],"exact")


if __name__ == "__main__":
    unittest.main()
