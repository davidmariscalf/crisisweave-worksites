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
- explicit privacy-minimised public export
- privacy-preserving Crisis Cleanup JSON adapter
- small localhost HTTP API for the field UI
- optional coordinator token for write endpoints
- exact-origin CORS when browser access is explicitly enabled
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

`assigned` is created only by the assignment operation, not by a generic transition or an import refresh. Releasing an assignment moves the worksite back to `ready`.

### Atomic assignment

```bash
python worksites.py --db demo.db assign cw-work-001 --team team-alpha --actor coordinator-1
```

SQLite `BEGIN IMMEDIATE` is used around assignment. A second assignment attempt fails instead of silently overwriting the first team.

### Public export

Do not expose a raw operational database export on a public site. Use the explicit projection:

```bash
python public_export.py --db demo.db > worksites.public.jsonl
```

For non-synthetic records it rounds Point coordinates to two decimal places, strips `assigned_team`, coordinator instructions, free-form descriptions, source URLs and arbitrary partner metadata, and marks the result with `visibility: public` and `location_precision: approximate`.

The shared `crisisweave-cores` public contract rejects non-synthetic public worksites that do not declare approximate/area-only location precision.

### Crisis Cleanup adapter

Crisis Cleanup's public frontend model includes fields such as survivor name, street address, phone numbers and email. The adapter deliberately does **not** carry those into CrisisWeave.

Given an authorised JSON export containing an array or `{ "results": [...] }`:

```bash
python adapters/crisis_cleanup.py crisis-cleanup-export.json > crisis-cleanup.public.jsonl
```

The adapter:

- removes direct survivor identity/contact/address fields
- rounds coordinates before output
- maps the upstream work type into the CrisisWeave taxonomy
- imports records as `triaged`, never as a CrisisWeave assignment
- records whether the upstream record was claimed only as provenance metadata
- marks staffing and integration review as required instead of inventing an authoritative crew size

It is an import transformer, **not** an authenticated Crisis Cleanup API client. A live integration still requires an approved API contract and credentials from Crisis Cleanup.

### HTTP writes

For a local demo, the server binds to `127.0.0.1` and can accept writes without a token. To require one:

```bash
CW_COORDINATOR_TOKEN='replace-me' python worksites.py --db demo.db serve
```

Then send `Authorization: Bearer replace-me` on POST requests. This is a demo protection mechanism, not production identity/authentication. CORS is disabled unless an exact `CW_WORKSITES_ALLOWED_ORIGIN` is configured.

## API

- `GET /api/health`
- `GET /api/worksites`
- `GET /api/worksites/<id>`
- `GET /api/worksites/<id>/audit`
- `POST /api/worksites/<id>/assign` with `{ "team_id": "...", "actor": "..." }`
- `POST /api/worksites/<id>/release` with `{ "actor": "..." }`
- `POST /api/worksites/<id>/transition` with `{ "state": "triaged", "actor": "...", "note": "..." }`

The API intentionally does not define survivor PII fields in its contract. Operational deployments should nevertheless treat exact coordinates and free-form text as sensitive.

## Contract

See `schema/worksite.schema.json`. Required concepts include:

- explicit request/assessment provenance
- location precision / public visibility metadata
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
