# Training Master Context

This file is the single-file handoff for future Codex sessions.
If a new agent opens this repo, it should read this file first, then `config/athlete_profile.json`, then the current block plan and latest data exports.

## Why This Project Exists

This repository is being used to turn raw Garmin FIT files and Apple Health exports into a practical race-prep system for Jonathan Airhart.

The goal is not generic fitness tracking. The goal is race-specific decision support for two 2026 MTB events:

- `Silver Rush 50 MTB` on `2026-07-12`
- `Park City Point 2 Point` on `2026-09-05`

The analysis is meant to answer:

- what training the athlete actually did
- what physiological systems are underdeveloped
- whether recovery is adequate
- how daily and weekly work should change
- what pacing, fueling, and climbing strategies best fit the target races

## Current Source Of Truth

- Machine-readable athlete profile: `config/athlete_profile.json`
- Narrative athlete brief: `docs/ATHLETE_CONTEXT.md`
- Current dated plan: `docs/TRAINING_BLOCK_2026-03-29_to_2026-05-03.md`
- Dashboard calendar source: `config/training_calendar.json`
- Recent Garmin export: `exports/edge840_recent`
- Recent Apple Health export: `exports/apple_health_recent_2`
- Recent merged daily dataset: `exports/training_dataset_recent/training_daily.csv`
- Recent ride diagnostics: `exports/analysis/recent_ride_diagnostics.csv`
- Dashboard snapshot files: `data/training_daily.csv`, `data/recent_ride_diagnostics.csv`

## Non-Negotiable Rules

- Default analysis window begins on `2025-07-01`.
- Treat the `2026-03-18` Dr. Max Testa lactate test as authoritative baseline data until replaced by a newer lab test.
- Do not collapse threshold into one generic zone.
- Use `threshold_flats` for flat / lower-altitude efforts.
- Use `threshold_climbing` for climbing / altitude efforts.
- Prefer Garmin FIT files over Apple Health when both exist for the same ride.
- Use Apple Health primarily for sleep, HRV, resting HR, readiness, and secondary ride coverage.

## Athlete And Race Context

- Athlete: Jonathan Airhart
- No current injury limitations
- Extensive gym experience
- Default strength target: `2` heavy / low-rep sessions per week
- Flexible schedule, usually enough availability for long rides and gym work

### Race 1: Silver Rush 50 MTB

- Date: `2026-07-12`
- Leadville, Colorado
- About `50 miles`
- About `8,000 ft` of climbing
- Mostly fire roads, limited singletrack
- Altitude about `10,000-13,000 ft`
- Goal finish time: about `6-7 hours`
- Main need: sustainable climbing durability and pacing at altitude

### Race 2: Park City Point 2 Point

- Date: `2026-09-05`
- Park City, Utah
- About `77 miles`
- About `10,000 ft` of climbing
- About `99%` singletrack
- Altitude about `7,000-10,000 ft`
- 2025 result: `12:03`
- 2026 goal: under `9:00`
- Main need: long-duration trail endurance, repeatable climbing power, technical pacing, and fatigue resistance

## Data Collection Setup

- Primary bike head unit: `Garmin Edge 840`
- Secondary wearable: `Apple Watch`
- Memphis bike currently has Garmin plus heart rate monitor
- Planned Memphis additions: cadence sensor, possibly road-bike power meter

Collection protocol:

- Record every ride on Garmin when possible
- Keep wearing Apple Watch for sleep and recovery data
- Treat Apple Health as secondary for rides when Garmin is missing

## Dr. Testa Baseline

The `2026-03-18` lactate test is the anchor for all current analysis.

### Lab Anchors

- `LT`: `190 W`, `138 bpm`
- `L2`: `205 W`, `142 bpm`
- `L3`: `230 W`, `154 bpm`
- `L4`: `245 W`, `160 bpm`
- `OBLA`: `240 W`, `156 bpm`

### Training Targets From The Sheet

- `slow_endurance`: `<123 bpm`, `<130 W`
- `long_endurance`: `117-133 bpm`, `130-170 W`
- `medium_endurance`: `139-148 bpm`, `190-220 W`
- `threshold_flats`: `153-158 bpm`, `230-250 W`
- `threshold_climbing`: `156-161 bpm`, `240-260 W`
- `lactic`: `>158 bpm`, `>275 W`
- `sfr`: `125-140 bpm`, `190-220 W`

Interpretation:

- Dr. Testa explicitly distinguishes threshold on flats from threshold on climbs / altitude
- those rows are coaching targets, not conflicting physiology data

## Training Templates In Use

### Memphis

- `zone_2_endurance` x `3` per week:
  - total ride `2.5+ hours`
  - `20-30 min` easy below `130 W`
  - `3 x 30 min` at `130-170 W`, `HR <135`
  - `5 min` off-bike stop / fuel between reps

- `aerobic_threshold_flats` x `1` per week:
  - `30 min` zone 1-2
  - `10 min` zone 3 at `80-90 rpm`
  - `4 x 8-15 min` at `230-250 W` or `150-160 bpm`
  - `4-5 min` easy spin between reps
  - start at `8 min` and add `1-2 min` every `2 weeks`

- `intermittent_threshold` x `1` per week:
  - `30 min` zone 1-2
  - `10 min` zone 3
  - `2 x 20 min` as `4 x (3 min hard / 2 min easy)`
  - `30 min` easy riding between the two sets

### Park City

- `endurance_altitude` x `4` per week:
  - `1.5-3 hours`
  - power below `220 W`
  - HR below `150-155`

- `climbing_intervals_altitude` x `1` per week:
  - `20 min` zone 1-2
  - `10 min` zone 3
  - `4 x 4 min` uphill at `230-240 W`
  - `3 min` recovery
  - `20 min` cooldown
  - described by Dr. Testa as VO2 max work, but operationally treated here as altitude-specific uphill aerobic-power work

## Strength Context

Tracked framework:

- dynamic warm-up
- core work
- back work:
  - bent over dumbbell row
  - close grip lat pulldown
  - pull-ups
- lower body:
  - single leg press
  - hex / trap bar deadlift
  - Romanian deadlift
  - goblet squat
  - thruster
- key cycling-specific power movement:
  - explosive walking lunges with dumbbells in a bent cycling posture

## Fueling Context

- Liquids and gels appear to work best
- High-calorie drink mix plus sodium and electrolytes works better than solid food
- During the 2025 Point 2 Point, solid food was difficult to stomach mid-race

Implication:

- long rides should double as fueling practice
- race planning should assume liquids plus gels are primary fuel

## What Has Already Been Built

### Data Pipeline

- Garmin FIT exporter that preserves all message types, not just `record`
- Apple Health XML exporter and daily-metrics pipeline
- merged cross-source daily dataset
- recent-ride diagnostics against Dr. Testa zones

### Training Dashboard

The Flask app includes a dashboard at `/dashboard` with:

- today’s prescribed workout
- upcoming training block
- race countdowns
- recent ride and recovery summary cards
- workout logging
- gym session logging with sets, reps, and weights

### Recent Analysis Direction

The main conclusions so far:

- the current limiter is not basic toughness, it is long-duration climbing durability
- Park City easy days need to stay truly easy
- cadence on climbs is improving but not yet stable under fatigue
- the athlete needs longer continuous rides, not just more short hard work

One concrete example:

- the Garmin ride on `2026-03-30` was prescribed as an easy spin day but functioned as a real endurance / climbing session instead

## Why The Files Matter

If the original chat window is closed, this repository should still be enough to resume work.
The key idea is that the important conversation content has been translated into durable project files, not left only in chat history.

Future agents should not restart from scratch or ask generic onboarding questions unless something materially changed.

## How A New Codex Session Should Resume

1. Read this file.
2. Read `config/athlete_profile.json`.
3. Read the current block plan in `docs/TRAINING_BLOCK_2026-03-29_to_2026-05-03.md` or whichever newer block exists.
4. Inspect `exports/analysis/recent_ride_diagnostics.csv` and `exports/training_dataset_recent/training_daily.csv`.
5. Use the Garmin recent exports for ride-level and record-level analysis.
6. Update profile and planning files before changing analysis rules if the athlete provides new lab data, race goals, sensors, or coaching prescriptions.

## Immediate Next Priorities

- continue evaluating rides against the prescribed plan
- keep building race-specific guidance for Silver Rush and Point 2 Point
- improve Apple Health ingestion and automation
- continue using the dashboard as the daily execution surface
