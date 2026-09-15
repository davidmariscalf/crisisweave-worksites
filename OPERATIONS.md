# CrisisWeave worksite operations

Operational recovery work can become unsafe when it is technically valid but stale. CrisisWeave therefore treats freshness as a coordinator concern rather than silently assuming an old request is still actionable.

## Stale-work report

Run against the authoritative database:

```bash
python staleness.py --db /data/worksites.db
```

Default revalidation horizons are deliberately conservative:

- requested: 24 hours
- triaged: 24 hours
- ready: 12 hours
- assigned: 8 hours
- in progress: 8 hours

Override them with the corresponding `--*-hours` arguments when the operating organisation has an approved policy.

For monitoring jobs, `--fail-on-stale` returns exit code 2 when one or more open worksites exceed the threshold:

```bash
python staleness.py --db /data/worksites.db --fail-on-stale
```

A stale report is **not** an instruction to cancel or complete a worksite automatically. It is a prompt for a coordinator to revalidate need, access, hazards, assignment and current official guidance. Terminal `completed` and `cancelled` worksites are excluded.

## Safety rule

Never turn hazard proximity, an old alert, or a stale worksite into an implied request for volunteers. CrisisWeave assignments must continue to originate from an explicit request, assessment or authorised partner import and remain coordinator-controlled.
