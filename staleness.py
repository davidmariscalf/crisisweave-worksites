#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from worksites import WorksiteStore

OPEN_STATES = {"requested", "triaged", "ready", "assigned", "in_progress"}
DEFAULT_HOURS = {
    "requested": 24,
    "triaged": 24,
    "ready": 12,
    "assigned": 8,
    "in_progress": 8,
}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def stale_report(store: WorksiteStore, thresholds: dict[str, int] | None = None, *, now_value: datetime | None = None) -> dict:
    thresholds = {**DEFAULT_HOURS, **(thresholds or {})}
    current = now_value or datetime.now(timezone.utc)
    stale = []
    open_count = 0
    for worksite in store.list():
        state = worksite.get("state")
        if state not in OPEN_STATES:
            continue
        open_count += 1
        updated = parse_time(worksite["updated_at"])
        age_hours = max(0.0, (current - updated).total_seconds() / 3600)
        threshold = int(thresholds[state])
        if age_hours >= threshold:
            stale.append(
                {
                    "id": worksite["id"],
                    "state": state,
                    "priority": worksite.get("priority"),
                    "area": worksite.get("area"),
                    "updated_at": worksite["updated_at"],
                    "age_hours": round(age_hours, 1),
                    "threshold_hours": threshold,
                }
            )
    stale.sort(key=lambda row: (-row["age_hours"], row["id"]))
    return {
        "generated_at": current.isoformat().replace("+00:00", "Z"),
        "open_worksites": open_count,
        "stale_worksites": len(stale),
        "threshold_hours": thresholds,
        "items": stale,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Report CrisisWeave worksites that may need coordinator revalidation")
    parser.add_argument("--db", required=True)
    parser.add_argument("--requested-hours", type=int, default=DEFAULT_HOURS["requested"])
    parser.add_argument("--triaged-hours", type=int, default=DEFAULT_HOURS["triaged"])
    parser.add_argument("--ready-hours", type=int, default=DEFAULT_HOURS["ready"])
    parser.add_argument("--assigned-hours", type=int, default=DEFAULT_HOURS["assigned"])
    parser.add_argument("--in-progress-hours", type=int, default=DEFAULT_HOURS["in_progress"])
    parser.add_argument("--fail-on-stale", action="store_true")
    args = parser.parse_args()
    thresholds = {
        "requested": args.requested_hours,
        "triaged": args.triaged_hours,
        "ready": args.ready_hours,
        "assigned": args.assigned_hours,
        "in_progress": args.in_progress_hours,
    }
    if any(v < 1 or v > 24 * 30 for v in thresholds.values()):
        raise SystemExit("staleness thresholds must be between 1 hour and 30 days")
    report = stale_report(WorksiteStore(args.db), thresholds)
    print(json.dumps(report, indent=2))
    return 2 if args.fail_on_stale and report["stale_worksites"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
