"""Hevy-verifiable competency definitions and evidence extraction."""
from typing import Any

DEFINITIONS = {
    "Pulling Strength": {"exercise": "Pull Up", "target": 3, "unit": "reps", "match": ("pull up",)},
    "Grip Strength": {"exercise": "Dead Hang", "target": 60, "unit": "seconds", "match": ("dead hang",)},
    "Core Strength": {"exercise": "Hanging Knee Raise", "target": 10, "unit": "reps", "match": ("hanging knee raise", "knee raise")},
    "Mobility": {"exercise": "Face Pull", "target": 15, "unit": "reps", "match": ("face pull",)},
    "Endurance": {"exercise": "Lat Pulldown", "target": 12, "unit": "reps", "match": ("lat pulldown",)},
}

def extract_evidence(workouts: list[dict], previous: dict[str, Any]) -> dict[str, dict]:
    evidence = dict(previous or {})
    for name, definition in DEFINITIONS.items():
        value = float(evidence.get(name, {}).get("value", 0))
        for workout in workouts:
            for exercise in workout.get("exercises", []):
                title = exercise.get("title", "").casefold()
                if not any(term in title for term in definition["match"]): continue
                for item in exercise.get("sets", []):
                    measured = item.get("duration_seconds") if definition["unit"] == "seconds" else item.get("reps")
                    value = max(value, float(measured or 0))
        evidence[name] = {"exercise": definition["exercise"], "value": value, "target": definition["target"], "unit": definition["unit"], "source": "hevy" if value else None}
    return evidence
