# Athlete Context

This repository is being used to build race-specific analysis for Jonathan Airhart.

## Source Of Truth

- Machine-readable profile: `config/athlete_profile.json`
- Recent merged daily dataset: `exports/training_dataset_recent/training_daily.csv`
- Garmin recent record stream: `exports/edge840_recent/messages/record.csv`
- Garmin recent event stream: `exports/edge840_recent/messages/event.csv`
- Apple Health daily metrics: `exports/apple_health_recent_2/daily_metrics.csv`

## Core Rules

- Default analysis scope begins on `2025-07-01`.
- The `2026-03-18` Dr. Max Testa lactate test is the authoritative baseline until a newer lab test replaces it.
- Do not use a single generic threshold zone.
- Use separate threshold contexts:
  - `threshold_flats` for flat terrain and lower altitude efforts
  - `threshold_climbing` for climbing and altitude efforts
- Prefer Garmin FIT files for bike-performance analysis when they exist.
- Use Apple Health primarily for readiness and recovery analysis, plus secondary ride coverage when Garmin is missing.

## Current Goal Races

### Silver Rush 50 MTB

- Date: `2026-07-12`
- Location: Leadville, Colorado
- Distance / climbing: about `50 miles`, about `8,000 ft`
- Terrain: mainly fire roads, limited singletrack
- Altitude: about `10,000-13,000 ft`
- Goal: finish in about `6-7 hours`
- Main demand: high-altitude climbing durability and sustainable pacing

### Park City Point 2 Point

- Date: `2026-09-05`
- Location: Park City, Utah
- Distance / climbing: about `77 miles`, about `10,000 ft`
- Terrain: about `99%` singletrack
- Altitude: about `7,000-10,000 ft`
- 2025 result: `12:03`
- 2026 goal: finish under `9:00`
- Main demand: long-duration trail durability, repeatable climbing efforts, technical pacing, and fatigue resistance

## Current Data Collection Setup

- Primary head unit: `Garmin Edge 840`
- Secondary wearable: `Apple Watch`
- Memphis setup today:
  - Garmin
  - heart rate monitor
- Planned Memphis upgrades:
  - cadence sensor
  - possible road-bike power meter

Recommended collection protocol:

- Record every ride on the Garmin when possible.
- Keep wearing the Apple Watch for sleep, HRV, resting HR, and recovery context.
- Use Apple Health as a secondary ride source, not the primary source, when a Garmin FIT file exists.

## Dr. Testa Lactate Test Summary

Date: `2026-03-18`

Anchor values:

- `LT`: `190 W`, `138 bpm`
- `L2`: `205 W`, `142 bpm`
- `L3`: `230 W`, `154 bpm`
- `L4`: `245 W`, `160 bpm`
- `OBLA`: `240 W`, `156 bpm`

Training targets from the sheet:

- `slow_endurance`: `<123 bpm`, `<130 W`
- `long_endurance`: `117-133 bpm`, `130-170 W`
- `medium_endurance`: `139-148 bpm`, `190-220 W`
- `threshold_flats`: `153-158 bpm`, `230-250 W`
- `threshold_climbing`: `156-161 bpm`, `240-260 W`
- `lactic`: `>158 bpm`, `>275 W`
- `sfr`: `125-140 bpm`, `190-220 W`

Interpretation note:

- The threshold rows are context-specific coaching targets, not a contradiction.
- Dr. Testa explicitly distinguishes threshold on flats from threshold on climbs and at altitude.

## What To Ask For Next

The highest-value missing information is:

- Dr. Testa's workout prescriptions for Park City and Memphis
- Typical weekly time availability for riding and gym work
- Any injuries, mobility restrictions, or lifting limitations
- Updated sensor inventory once the Memphis bike gets cadence or power
