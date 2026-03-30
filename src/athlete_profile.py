from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_athlete_profile(profile_path: str | Path) -> dict[str, Any]:
    path = Path(profile_path).expanduser().resolve()
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
