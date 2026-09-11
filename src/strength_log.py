"""Strength log: parse the Obsidian "Workout log" grammar and do the strength math.

Grammar (the callout at the top of ~/Vault/Fitness/Workout log.md is the user-facing copy):

    ## YYYY-MM-DD · Session name · Location        (date first; '·', '|', or ' - ' separate parts)
    bw: 198 · time: 45 · rpe: 7                     (optional, any subset, any order)
    - Exercise: LOAD x REPS, REPS; LOAD x REPS      (sets in order; ';' starts a new load)
        LOAD = number[#|lb|lbs|kg] | bw | bw+N | bw-N
        REPS = N | N+ (rep max / AMRAP) | Ns (seconds) | M:SS (timed) ; '@RPE' per set,
               or once at the end of a segment to apply to every set in it
    Notes: free text to the end of the section

Anything else inside a section is ignored (and reported as a warning).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

KG_TO_LB = 2.20462
EXERCISES_PATH = Path(__file__).resolve().parents[1] / "config" / "strength_exercises.json"

_HEADER_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})(?:\s*(?:[·•|]|\s[-–—]\s)\s*(.*?))?\s*$")
_PART_SPLIT_RE = re.compile(r"\s*[·•|]\s*|\s+[-–—]\s+")
_META_RE = re.compile(r"\b(bw|bodyweight|weight|time|mins?|duration|rpe)\s*[:=]\s*(\d+(?:\.\d+)?)", re.I)
_META_LINE_RE = re.compile(r"^\s*(bw|bodyweight|weight|time|mins?|duration|rpe)\s*[:=]", re.I)
_EXERCISE_RE = re.compile(r"^\s*[-*+]\s+(.+?)\s*:\s*(.+?)\s*$")
_NOTES_RE = re.compile(r"^\s*notes?\s*[:：]\s*(.*)$", re.I)
_LOAD_RE = re.compile(
    r"^(?:(bw|bodyweight)\s*(?:([+-])\s*(\d+(?:\.\d+)?))?|(\d+(?:\.\d+)?)\s*(#|lbs?|kg)?)$", re.I
)
_SET_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(s|secs?|m|mins?)?\s*(\+)?\s*(?:@\s*(\d+(?:\.\d+)?))?$", re.I)
_TIME_RE = re.compile(r"^(\d+):(\d{2})\s*(\+)?\s*(?:@\s*(\d+(?:\.\d+)?))?$")
_X_SPLIT_RE = re.compile(r"\s*[x×X]\s*")


@dataclass
class ParsedSet:
    set_number: int
    load_kind: str                 # "lb" or "bw"
    load_lb: float | None          # numeric load; None for a pure bodyweight set
    added_lb: float = 0.0          # bw+25 -> 25.0, bw-20 (assisted) -> -20.0
    reps: int | None = None
    duration_s: int | None = None
    rpe: float | None = None
    is_amrap: bool = False
    raw: str = ""


@dataclass
class ParsedExercise:
    name: str                      # as typed
    canonical: str                 # library name, or the typed name if unknown
    category: str                  # push/pull/hinge/squat/core/carry/power/calf/arms/other
    known: bool
    sets: list[ParsedSet] = field(default_factory=list)


@dataclass
class ParsedSession:
    session_date: str
    title: str
    location: str | None = None
    bodyweight: float | None = None
    duration_minutes: int | None = None
    rpe: float | None = None
    notes: str | None = None
    exercises: list[ParsedExercise] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    line_no: int = 0

    @property
    def session_type(self) -> str:
        t = self.title.lower()
        if "core" in t or "big 3" in t or "big three" in t:
            return "core"
        return "strength"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["session_type"] = self.session_type
        return d


# ---------------------------------------------------------------- exercise library

def normalize_name(name: str) -> str:
    s = name.strip().lower()
    s = s.replace("–", "-").replace("—", "-").replace("’", "'")
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip(" .:")
    return s


def load_exercise_library(path: Path | None = None) -> dict[str, Any]:
    p = path or EXERCISES_PATH
    if not p.exists():
        return {"entries": [], "by_alias": {}}
    with p.open(encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data.get("exercises", [])
    by_alias: dict[str, dict[str, Any]] = {}
    for e in entries:
        by_alias[normalize_name(e["name"])] = e
        for a in e.get("aliases", []):
            by_alias[normalize_name(a)] = e
    return {"entries": entries, "by_alias": by_alias}


def canonicalize(name: str, library: dict[str, Any]) -> tuple[str, str, bool]:
    """Return (canonical name, category, known)."""
    by_alias = library.get("by_alias", {})
    key = normalize_name(name)
    hit = by_alias.get(key)
    if hit is None:
        # second try: drop a trailing parenthetical, e.g. "Incline press (Hammer Strength)"
        stripped = normalize_name(re.sub(r"\s*\([^)]*\)\s*$", "", name))
        hit = by_alias.get(stripped)
    if hit is None:
        # third try: singular/plural
        if key.endswith("s"):
            hit = by_alias.get(key[:-1])
    if hit is None:
        return name.strip(), "other", False
    return hit["name"], hit.get("category", "other"), True


# ---------------------------------------------------------------- parsing

def _parse_load(token: str) -> tuple[str, float | None, float, str | None]:
    """-> (load_kind, load_lb, added_lb, error)."""
    m = _LOAD_RE.match(token.strip())
    if not m:
        return "lb", None, 0.0, f"unreadable load '{token.strip()}'"
    if m.group(1):
        added = float(m.group(3)) if m.group(3) else 0.0
        if m.group(2) == "-":
            added = -added
        return "bw", None, added, None
    value = float(m.group(4))
    unit = (m.group(5) or "").lower()
    if unit == "kg":
        value = round(value * KG_TO_LB, 1)
    return "lb", value, 0.0, None


def _parse_set_token(token: str) -> tuple[dict[str, Any] | None, str | None]:
    tok = token.strip()
    if not tok:
        return None, None
    m = _TIME_RE.match(tok)
    if m:
        secs = int(m.group(1)) * 60 + int(m.group(2))
        return {"reps": None, "duration_s": secs, "is_amrap": bool(m.group(3)),
                "rpe": float(m.group(4)) if m.group(4) else None}, None
    m = _SET_RE.match(tok)
    if not m:
        return None, f"unreadable set '{tok}'"
    value = float(m.group(1))
    unit = (m.group(2) or "").lower()
    is_amrap = bool(m.group(3))
    rpe = float(m.group(4)) if m.group(4) else None
    if unit.startswith("s"):
        return {"reps": None, "duration_s": int(round(value)), "is_amrap": is_amrap, "rpe": rpe}, None
    if unit.startswith("m"):
        return {"reps": None, "duration_s": int(round(value * 60)), "is_amrap": is_amrap, "rpe": rpe}, None
    return {"reps": int(round(value)), "duration_s": None, "is_amrap": is_amrap, "rpe": rpe}, None


def _parse_exercise_body(body: str, warnings: list[str], label: str) -> list[ParsedSet]:
    sets: list[ParsedSet] = []
    n = 0
    for segment in body.split(";"):
        seg = segment.strip()
        if not seg:
            continue
        parts = _X_SPLIT_RE.split(seg, maxsplit=1)
        if len(parts) != 2:
            warnings.append(f"{label}: segment '{seg}' has no 'x' between load and reps")
            continue
        load_kind, load_lb, added_lb, err = _parse_load(parts[0])
        if err:
            warnings.append(f"{label}: {err}")
            continue
        tokens = [t for t in parts[1].split(",")]
        parsed: list[dict[str, Any]] = []
        for t in tokens:
            info, err = _parse_set_token(t)
            if err:
                warnings.append(f"{label}: {err}")
                continue
            if info is None:
                continue
            info["raw"] = t.strip()
            parsed.append(info)
        # A single trailing '@RPE' on the last set applies to the whole segment.
        if parsed and parsed[-1]["rpe"] is not None and all(p["rpe"] is None for p in parsed[:-1]):
            seg_rpe = parsed[-1]["rpe"]
            for p in parsed:
                p["rpe"] = seg_rpe
        for p in parsed:
            n += 1
            sets.append(ParsedSet(set_number=n, load_kind=load_kind, load_lb=load_lb, added_lb=added_lb,
                                  reps=p["reps"], duration_s=p["duration_s"], rpe=p["rpe"],
                                  is_amrap=p["is_amrap"], raw=p["raw"]))
    return sets


def _apply_meta(session: ParsedSession, line: str) -> None:
    for key, val in _META_RE.findall(line):
        k = key.lower()
        v = float(val)
        if k in ("bw", "bodyweight", "weight"):
            session.bodyweight = v
        elif k in ("time", "min", "mins", "duration"):
            session.duration_minutes = int(round(v))
        elif k == "rpe":
            session.rpe = v


def parse_workout_log(text: str, library: dict[str, Any] | None = None) -> list[ParsedSession]:
    """Parse a whole log (or a single pasted session) into sessions, in document order."""
    lib = library if library is not None else load_exercise_library()
    sessions: list[ParsedSession] = []
    current: ParsedSession | None = None
    in_notes = False

    for idx, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        header = _HEADER_RE.match(line)
        if header:
            rest = (header.group(2) or "").strip()
            parts = [p.strip() for p in _PART_SPLIT_RE.split(rest) if p.strip()] if rest else []
            title = parts[0] if parts else "Session"
            location = parts[1] if len(parts) > 1 else None
            current = ParsedSession(session_date=header.group(1), title=title, location=location, line_no=idx)
            sessions.append(current)
            in_notes = False
            continue
        if current is None:
            continue                      # preamble (frontmatter, callout, headings) is ignored
        if line.startswith("#"):
            # a different heading level inside the log (e.g. "# Log") — end any notes, ignore
            in_notes = False
            continue
        if not line.strip():
            continue
        notes_m = _NOTES_RE.match(line)
        if notes_m:
            current.notes = notes_m.group(1).strip() or None
            in_notes = True
            continue
        if in_notes:
            if line.lstrip().startswith(">"):
                continue
            current.notes = f"{current.notes}\n{line.strip()}" if current.notes else line.strip()
            continue
        if _META_LINE_RE.match(line):
            _apply_meta(current, line)
            continue
        ex_m = _EXERCISE_RE.match(line)
        if ex_m:
            name, body = ex_m.group(1), ex_m.group(2)
            canonical, category, known = canonicalize(name, lib)
            label = f"line {idx} ({name})"
            sets = _parse_exercise_body(body, current.warnings, label)
            if not sets:
                current.warnings.append(f"{label}: no sets parsed")
            current.exercises.append(ParsedExercise(name=name.strip(), canonical=canonical,
                                                    category=category, known=known, sets=sets))
            if not known:
                current.warnings.append(f"{label}: unknown exercise name (logged as typed)")
            continue
        if line.lstrip().startswith(">"):
            continue
        current.warnings.append(f"line {idx}: ignored '{line.strip()[:60]}'")
    return sessions


# ---------------------------------------------------------------- strength math

def epley_e1rm(load_lb: float | None, reps: int | None) -> float | None:
    """Estimated 1RM (Epley). Only meaningful for numeric loads and 1..~12 reps."""
    if load_lb is None or not reps or reps < 1 or load_lb <= 0:
        return None
    if reps == 1:
        return round(float(load_lb), 1)
    return round(load_lb * (1 + reps / 30.0), 1)


def best_set(exercise_sets: list[dict[str, Any]] | list[ParsedSet]) -> dict[str, Any] | None:
    """The set with the highest e1RM in a list of sets (dicts or ParsedSet)."""
    best: dict[str, Any] | None = None
    for s in exercise_sets:
        d = asdict(s) if isinstance(s, ParsedSet) else s
        load = d.get("load_lb") if d.get("load_kind", "lb") == "lb" else None
        e1 = epley_e1rm(load, d.get("reps"))
        if e1 is None:
            continue
        if best is None or e1 > best["e1rm"]:
            best = {"e1rm": e1, "load_lb": load, "reps": d.get("reps")}
    return best


def format_sets(sets: list[dict[str, Any]]) -> str:
    """Compact human form: '135 x 10, 10, 8; 155 x 5' (used by templates and the push script)."""
    groups: list[tuple[str, list[str]]] = []
    for s in sets:
        if s.get("load_kind") == "bw":
            added = s.get("added_lb") or 0
            load = "bw" if not added else (f"bw+{added:g}" if added > 0 else f"bw{added:g}")
        else:
            lb = s.get("load_lb")
            load = f"{lb:g}" if lb is not None else "?"
        if s.get("duration_s"):
            rep = f"{s['duration_s']}s"
        else:
            rep = f"{s.get('reps') if s.get('reps') is not None else '?'}"
        if s.get("is_amrap"):
            rep += "+"
        if groups and groups[-1][0] == load:
            groups[-1][1].append(rep)
        else:
            groups.append((load, [rep]))
    return "; ".join(f"{load} x {', '.join(reps)}" for load, reps in groups)


# ---------------------------------------------------------------- inbound JSON

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def coerce_session(d: dict[str, Any], library: dict[str, Any] | None = None) -> ParsedSession:
    """Validate/normalize a session dict (from the push script or an API client) into a ParsedSession.
    Raises ValueError on a malformed payload. Exercise names are re-canonicalized server-side."""
    lib = library if library is not None else load_exercise_library()
    if not isinstance(d, dict):
        raise ValueError("session must be an object")
    sd = str(d.get("session_date", "")).strip()
    if not _DATE_RE.match(sd):
        raise ValueError(f"bad session_date '{sd}'")
    title = str(d.get("title") or "Session").strip()[:80]

    def _num(v: Any) -> float | None:
        if v is None or v == "":
            return None
        return float(v)

    sess = ParsedSession(
        session_date=sd, title=title,
        location=(str(d["location"]).strip()[:40] if d.get("location") else None),
        bodyweight=_num(d.get("bodyweight")),
        duration_minutes=(int(_num(d.get("duration_minutes"))) if _num(d.get("duration_minutes")) is not None else None),
        rpe=_num(d.get("rpe")),
        notes=(str(d["notes"]).strip()[:2000] if d.get("notes") else None),
    )
    for ex in d.get("exercises") or []:
        name = str(ex.get("name") or ex.get("canonical") or "").strip()
        if not name:
            continue
        canonical, category, known = canonicalize(name, lib)
        pe = ParsedExercise(name=name[:80], canonical=canonical, category=category, known=known)
        for i, s in enumerate(ex.get("sets") or [], start=1):
            kind = "bw" if str(s.get("load_kind", "lb")).lower() == "bw" else "lb"
            reps = s.get("reps")
            dur = s.get("duration_s")
            pe.sets.append(ParsedSet(
                set_number=int(s.get("set_number") or i), load_kind=kind,
                load_lb=(_num(s.get("load_lb")) if kind == "lb" else None),
                added_lb=float(s.get("added_lb") or 0.0),
                reps=(int(reps) if reps not in (None, "") else None),
                duration_s=(int(dur) if dur not in (None, "") else None),
                rpe=_num(s.get("rpe")), is_amrap=bool(s.get("is_amrap")), raw=str(s.get("raw") or "")[:40],
            ))
        sess.exercises.append(pe)
    return sess
