from __future__ import annotations

import argparse
import json
from copy import deepcopy
from typing import Any

from worksites import WorksiteStore


PUBLIC_OPTIONAL_FIELDS = (
    "safety_notes",
    "created_at",
    "updated_at",
    "version",
    "integration_review_required",
    "staffing_estimate_required",
)


def public_worksite(worksite: dict[str, Any]) -> dict[str, Any]:
    """Return a minimal public-safe worksite projection.

    Operational-only fields such as assigned_team, coordinator instructions,
    free-form descriptions and arbitrary partner metadata are intentionally
    omitted. Non-synthetic points are generalized to roughly kilometre scale.
    """
    source = worksite.get("source") or {}
    geometry = deepcopy(worksite.get("geometry") or {})
    coords = geometry.get("coordinates")
    synthetic = source.get("type") == "synthetic"
    if isinstance(coords, list) and len(coords) == 2 and not synthetic:
        geometry["coordinates"] = [round(float(coords[0]), 2), round(float(coords[1]), 2)]

    out = {
        "id": worksite["id"],
        "title": worksite["title"],
        "work_type": worksite["work_type"],
        "state": worksite["state"],
        "priority": worksite["priority"],
        "people_needed": worksite["people_needed"],
        "skills": list(worksite.get("skills") or []),
        "hazards": list(worksite.get("hazards") or []),
        "area": worksite["area"],
        "geometry": geometry,
        "location_precision": "exact" if synthetic else "approximate",
        "visibility": "public",
        "source": {
            "type": source.get("type"),
            "name": source.get("name"),
            "source_id": source.get("source_id"),
        },
    }
    for key in PUBLIC_OPTIONAL_FIELDS:
        if key in worksite:
            out[key] = deepcopy(worksite[key])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a privacy-minimised public CrisisWeave worksite snapshot")
    parser.add_argument("--db", default="worksites.db")
    parser.add_argument("--state", default=None)
    args = parser.parse_args()
    store = WorksiteStore(args.db)
    for row in store.list(args.state):
        print(json.dumps(public_worksite(row), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
