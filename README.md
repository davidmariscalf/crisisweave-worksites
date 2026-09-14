# crisisweave-worksites

Operational worksite coordination for CrisisWeave.

This repository owns the recovery-work contract and lifecycle. It is deliberately separate from incident intelligence: a flood, wildfire, earthquake or alert **never becomes a household cleanup job automatically**. A worksite must come from an explicit authorised request or assessment.

## What works

- documented JSON worksite contract
- deterministic validation
- lifecycle: `requested -> triaged -> ready -> assigned -> in_progress -> completed`
- `cancelled` terminal state from any non-terminal state
- atomic assignment in SQLite, preventing two teams from claiming the same worksite
- assignment release back to `ready`
- append-only audit trail in SQLite
- JSONL import/export
- small localhost HTTP API for the field UI
- optional coordinator token for write endpoints
- synthetic demo data with no survivor PII
- unit tests and GitHub Actions

## Quick start

Requires Python 3.10+ and no third-party packages.

```bash
python worksites.py --db demo.db init
python worksites.py --db demo.db import examples/worksites.jsonl
python worksites.py --db demo.db list
python worksites.py --db demo.db serve --port 8787
```

API: `http://127.0.0.1:8787/api/worksites`.

### Lifecycle

```text
requested -> triaged -> ready -> assigned -> in_progress -> completed
    |           |         |         |              |
    +-----------+---------+---------+--------------+--> cancelled
```

`assigned` is created only by the assignment operation, not by a generic transition. Releasing an assignment moves the worksite back to `ready`.

### Atomic assignment

```bash
python worksites.py --db demo.db assign cw-work-001 --team team-alpha --actor coordinator-1
```

SQLite `BEGIN IMMEDIATE` is used around assignment. A second assignment attempt fails instead of silently overwriting the first team.

### HTTP writes

For a local demo, the server binds to `127.0.0.1` and can accept writes without a token. To require one:

```bash
CW_COORDINATOR_TOKEN='replace-me' python worksites.py --db demo.db serve
```

Then send `Authorization: Bearer replace-me` on POST requests. This is a demo protection mechanism, not production identity/authentication.

## API

- `GET /api/health`
- `GET /api/worksites`
- `GET /api/worksites/<id>`
- `GET /api/worksites/<id>/audit`
- `POST /api/worksites/<id>/assign` with `{ "team_id": "...", "actor": "..." }`
- `POST /api/worksites/<id>/release` with `{ "actor": "..." }`
- `POST /api/worksites/<id>/transition` with `{ "state": "triaged", "actor": "...", "note": "..." }`

The API intentionally does not expose survivor PII fields in its contract.

## Contract

See `schema/worksite.schema.json`. Required concepts include:

- explicit request/assessment provenance
- approximate public-safe location
- work type and description
- crew size and skills
- hazards and safety notes
- priority and state
- coordinator instructions

## Safety boundary

This is coordination software, not an emergency authority or autonomous dispatch system. A visible worksite is not permission to enter a property or hazardous area. Real deployments need organisation identity, permissions, survivor privacy controls, authoritative assignment/synchronisation, operational monitoring, and coordinator oversight.

## Test

```bash
python -m unittest discover -s tests -v
```

## Integration

The umbrella `CrisisWeave` repository consumes this module in its cross-repository E2E demo. `crisisweave-map` provides the volunteer-facing browser UI.
