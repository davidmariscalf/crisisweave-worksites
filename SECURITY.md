# Security Policy

The worksite service is an operational boundary: private assignment details must not leak into public volunteer feeds, and crisis information must never automatically become a volunteer instruction.

## Reporting a vulnerability

Do not publish exploit details, credentials, precise private locations, personal data, coordinator instructions, or other sensitive evidence in a public issue.

Use GitHub private vulnerability reporting when available. Otherwise contact the repository owner through GitHub before disclosure so a private reporting channel can be arranged.

Include the affected revision, a minimal synthetic reproduction, expected impact, and any safe remediation ideas.

## High-priority classes

- public exposure of assigned teams, coordinator instructions, free-form operational descriptions or precise sensitive locations
- authorization or bearer-token bypasses
- cross-organisation data access
- state-transition flaws that allow unsafe assignment/completion behavior
- stale-work handling that can silently turn old information into current operational guidance
- unsafe logging or persistence of credentials/private data
- dependency or build-chain compromise

## Safety boundary

Do not test against real volunteers, survivors, emergency operations or third-party systems without authorization. Use synthetic fixtures and local deployments.

Alerts, hazards and verified incidents are inputs for human coordination; they must not automatically create or assign volunteer work.
