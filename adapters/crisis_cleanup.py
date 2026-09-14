from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


WORK_TYPE_RULES = (
    (("tree", "limb", "chainsaw"), "tree_removal"),
    (("tarp", "roof"), "tarping"),
    (("muck", "flood", "mud", "water"), "muck_out"),
    (("debris", "cleanup", "clean_up"), "debris_removal"),
    (("gut", "drywall", "demolition"), "gutting"),
    (("deliver", "supply", "supplies"), "delivery"),
    (("assess", "assessment"), "assessment"),
)


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _work_type(record: dict[str, Any]) -> str:
    candidates: list[str] = []
    key = record.get("key_work_type")
    if isinstance(key, dict):
        candidates.append(_first_text(key.get("work_type"), key.get("key"), key.get("name")))
    for item in record.get("work_types") or []:
        if isinstance(item, dict):
            candidates.append(_first_text(item.get("work_type"), item.get("key"), item.get("name")))
        else:
            candidates.append(str(item))
    haystack = " ".join(candidates).casefold()
    for needles, target in WORK_TYPE_RULES:
        if any(needle in haystack for needle in needles):
            return target
    return "other"


def _priority(record: dict[str, Any]) -> str:
    for flag in record.get("flags") or []:
        if isinstance(flag, dict) and flag.get("is_high_priority") is True:
            return "high"
    return "normal"


def _area(record: dict[str, Any]) -> str:
    # Deliberately excludes street address, postal code and survivor name.
    pieces = []
    for value in (record.get("city"), record.get("county"), record.get("state")):
        text = str(value or "").strip()
        if text and text not in pieces:
            pieces.append(text)
    return ", ".join(pieces) or "Partner worksite area withheld"


def _approximate_geometry(record: dict[str, Any]) -> dict[str, Any]:
    location = record.get("location") or record.get("map_location")
    if not isinstance(location, dict) or location.get("type") != "Point":
        raise ValueError("Crisis Cleanup record has no usable Point location")
    coords = location.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) != 2:
        raise ValueError("Crisis Cleanup record has no usable Point coordinates")
    try:
        lon, lat = float(coords[0]), float(coords[1])
    except (TypeError, ValueError) as exc:
        raise ValueError("Crisis Cleanup coordinates must be numeric") from exc
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("Crisis Cleanup coordinates outside valid bounds")
    return {"type": "Point", "coordinates": [round(lon, 2), round(lat, 2)]}


def convert_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("Crisis Cleanup record must be an object")
    upstream_id = _first_text(record.get("id"))
    if not upstream_id:
        raise ValueError("Crisis Cleanup record.id is required")

    mapped_type = _work_type(record)
    upstream_claimed = any(
        isinstance(item, dict) and item.get("claimed_by") not in (None, "")
        for item in (record.get("work_types") or [])
    )

    # Never import an external claim as a CrisisWeave assignment. A coordinator
    # must explicitly transition/assign after review inside CrisisWeave.
    return {
        "id": f"cc-{upstream_id}",
        "title": f"Crisis Cleanup {mapped_type.replace('_', ' ')} worksite",
        "work_type": mapped_type,
        "state": "triaged",
        "priority": _priority(record),
        "people_needed": 1,
        "skills": [],
        "hazards": [],
        "area": _area(record),
        "geometry": _approximate_geometry(record),
        "location_precision": "approximate",
        "visibility": "public",
        "source": {
            "type": "partner_import",
            "name": "Crisis Cleanup",
            "source_id": upstream_id,
            "upstream_claimed": upstream_claimed,
        },
        "integration_review_required": True,
        "staffing_estimate_required": True,
    }


def load_records(path: str | Path) -> list[dict[str, Any]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(value, dict) and isinstance(value.get("results"), list):
        value = value["results"]
    if not isinstance(value, list):
        raise ValueError("input must be a JSON array or an object with a results array")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError("all Crisis Cleanup records must be objects")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert exported Crisis Cleanup worksites to public-safe CrisisWeave JSONL")
    parser.add_argument("input")
    args = parser.parse_args()
    for record in load_records(args.input):
        print(json.dumps(convert_record(record), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
