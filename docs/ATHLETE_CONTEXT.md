# Athlete Context

This repository is being used to build race-specific analysis for Jonathan Airhart.

## Source Of Truth

- Machine-readable profile: `config/athlete_profile.json`
- Current dated block plan: `docs/TRAINING_BLOCK_2026-03-29_to_2026-05-03.md`
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

## Strength Training Context

- No current injuries limit training.
- Athlete has extensive gym experience.
- Default target is `2` heavy / low-rep strength sessions per week.
- Current strength framework to track:
  - dynamic warm-up
  - core strength work
  - back strength work:
    - bent over dumbbell row
    - close grip lat pulldown
    - pull-ups
  - lower body strength work:
    - single leg press
    - hex / trap bar deadlift
    - Romanian deadlift
    - goblet squat
    - thruster
  - primary power movement:
    - explosive walking lunges with dumbbells in a cycling-style bent posture

## Schedule And Fueling Context

- Weekly schedule is very flexible.
- Assume rides and gym sessions can be placed on any day.
- Long rides of `4-5 hours` are usually feasible when needed.
- Fueling that appears to work well:
  - high-calorie drink mix
  - substantial electrolytes and sodium
  - gel packs
- Race fueling constraint:
  - solid foods are much less realistic during hard racing than liquids and gels

## Current Subjective Training Notes

- Recent `40-50 mile` Memphis rides have felt strong.
- Recent `30 mile` rides have felt especially strong and not overly fatiguing.
- On uphill efforts, athlete is intentionally trying to raise cadence from roughly `60-70 rpm` toward `85-95 rpm`.
- Athlete is confident on descents and technical trail sections.
- The main problems from the 2025 Point 2 Point were:
  - pacing
  - climbing strength
  - total endurance for many consecutive hours of climbing
- Cramping and descending confidence were not major issues.

## Dr. Testa Workout Templates

### Memphis

- `zone_2_endurance` x `3` per week:
  - total ride `2.5+ hours`
  - `20-30 min` easy at less than `130 W`
  - `3 x 30 min` at `130-170 W` with `HR <135`
  - `5 min` stop / fuel / drink between blocks

- `aerobic_threshold_flats` x `1` per week:
  - `30 min` zone 1-2 warm-up
  - `10 min` zone 3 at `80-90 rpm`
  - `4 x 8-15 min` at `230-250 W` or `150-160 bpm`
  - `4-5 min` very gentle spinning between intervals
  - start at `8 min` and add `1-2 min` every `2 weeks`

- `intermittent_threshold` x `1` per week:
  - `30 min` zone 1-2 warm-up
  - `10 min` zone 3
  - `2 x 20 min` as `4 x (3 min hard / 2 min easy)`
  - `30 min` easy riding between the two 20 min sets

### Park City

- `endurance_altitude` x `4` per week:
  - `1.5-3 hours`
  - watts below `220`
  - HR below `150-155`

- `climbing_intervals_altitude` x `1` per week:
  - `20 min` zone 1-2 warm-up
  - `10 min` zone 3
  - `4 x 4 min` uphill at `230-240 W`
  - `3 min` recovery between reps
  - `20 min` cooldown
  - Dr. Testa described this as VO2 max work; in practice treat it as altitude-specific uphill aerobic-power work

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

- Updated sensor inventory once the Memphis bike gets cadence or power
