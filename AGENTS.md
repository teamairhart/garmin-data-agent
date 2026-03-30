## Issue Tracking

This project uses **bd (beads)** for issue tracking.
Run `bd prime` for workflow context, or install hooks (`bd hooks install`) for auto-injection.

**Quick reference:**
- `bd ready` - Find unblocked work
- `bd create "Title" --type task --priority 2` - Create issue
- `bd close <id>` - Complete work
- `bd sync` - Sync with git (run at session end)

## Athlete Analysis Context

Use `config/athlete_profile.json` as the machine-readable source of truth and `docs/ATHLETE_CONTEXT.md` as the narrative brief.

Project-specific rules:

- Default analysis scope begins on `2025-07-01`.
- Treat the `2026-03-18` Dr. Max Testa lactate test as authoritative baseline data.
- Do not collapse threshold into a single generic zone.
- Use `threshold_flats` for flat / lower-altitude work and `threshold_climbing` for climbing / altitude work.
- Prefer Garmin FIT files for ride-level and sample-level bike analysis when available.
- Use Apple Health for readiness, recovery, and secondary workout coverage.
- The 2026 target races are:
  - `Silver Rush 50 MTB` on `2026-07-12`
  - `Park City Point 2 Point` on `2026-09-05`

When the user provides new lab tests, race goals, or coaching prescriptions, update the profile files first before changing the analysis logic.
