from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
import httpx


class FitnessDataProvider(ABC):
    """Port for Hevy, Garmin, Strava, or manual fitness integrations."""
    @abstractmethod
    def get_workout_history(self, user_id: int) -> list[dict]: ...
    @abstractmethod
    def get_measurements(self, user_id: int) -> dict: ...
    @abstractmethod
    def get_exercise_progress(self, user_id: int, exercise: str) -> list[dict]: ...
    @abstractmethod
    def create_routine(self, routine: dict) -> dict: ...
    @abstractmethod
    def update_routine(self, routine_id: str, routine: dict) -> dict: ...


class MockFitnessProvider(FitnessDataProvider):
    def get_workout_history(self, user_id: int) -> list[dict]:
        return [{"date": "2026-09-01", "type": "strength", "duration_minutes": 45}]
    def get_measurements(self, user_id: int) -> dict:
        return {"source": "mock", "bodyweight_kg": None}
    def get_exercise_progress(self, user_id: int, exercise: str) -> list[dict]:
        return [{"exercise": exercise, "value": 0, "source": "mock"}]
    def create_routine(self, routine: dict) -> dict:
        return {"id": "mock-routine", **routine}
    def update_routine(self, routine_id: str, routine: dict) -> dict:
        return {"id": routine_id, **routine}


class HevyFitnessProvider(FitnessDataProvider):
    """Read-only adapter for the Hevy public REST API.

    A provider is deliberately not tied to GoalForge database models: it returns
    normalized source data, leaving application services to decide how it affects
    a particular goal. API keys remain server-side and are never sent to Next.js.
    """
    base_url = "https://api.hevyapp.com/v1"

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("HEVY_API_KEY is required")
        self.client = httpx.Client(base_url=self.base_url, headers={"api-key": api_key}, timeout=20)

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict:
        response = self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def _write(self, method: str, path: str, payload: dict) -> dict:
        response = self.client.request(method, path, json=payload)
        response.raise_for_status()
        return response.json()

    def get_workout_history(self, user_id: int) -> list[dict]:
        # Hevy returns pages of at most 10 workouts; fetch the available history.
        page, workouts = 1, []
        while True:
            data = self._request("/workouts", {"page": page, "pageSize": 10})
            batch = data.get("workouts", [])
            workouts.extend(batch)
            if not batch or page >= data.get("page_count", page): break
            page += 1
        return workouts

    def get_workout_changes(self, since: str) -> tuple[list[dict], str]:
        """Fetch changed workouts using Hevy's incremental event feed."""
        page, events, newest = 1, [], since
        while True:
            data = self._request("/workouts/events", {"since": since, "page": page, "pageSize": 10})
            batch = data.get("events", data.get("workout_events", []))
            events.extend(batch)
            if not batch or page >= data.get("page_count", page): break
            page += 1
        workouts = []
        for event in events:
            stamp = event.get("updated_at") or event.get("event_time") or event.get("created_at")
            if stamp and stamp > newest: newest = stamp
            if event.get("type") == "deleted": continue
            workout = event.get("workout", event)
            workout_id = workout.get("id") or event.get("workout_id")
            if workout_id and not workout.get("exercises"):
                detail = self._request(f"/workouts/{workout_id}")
                workout = detail.get("workout", detail)
            workouts.append(workout)
        return workouts, newest

    def get_measurements(self, user_id: int) -> dict:
        data = self._request("/measurements", {"page": 1, "pageSize": 10})
        return {"source": "hevy", "measurements": data.get("measurements", [])}

    def get_exercise_progress(self, user_id: int, exercise: str) -> list[dict]:
        # The exercise-template endpoint is intentionally exposed through this
        # port; callers can resolve a template id before requesting its history.
        data = self._request("/exercise_templates", {"page": 1, "pageSize": 100})
        return [x for x in data.get("exercise_templates", []) if exercise.lower() in x.get("title", "").lower()]

    def create_routine(self, routine: dict) -> dict:
        return self._write("POST", "/routines", {"routine": routine})

    def update_routine(self, routine_id: str, routine: dict) -> dict:
        return self._write("PUT", f"/routines/{routine_id}", {"routine": routine})

    def get_exercise_templates(self) -> list[dict]:
        page, templates = 1, []
        while True:
            data = self._request("/exercise_templates", {"page": page, "pageSize": 10})
            batch = data.get("exercise_templates", [])
            templates.extend(batch)
            if not batch or page >= data.get("page_count", page): break
            page += 1
        return templates

    def export_program(self, program: dict, existing_ids: dict[str, str], goal_title: str) -> dict[str, str]:
        """Resolve Hevy templates and create/update one routine for each session."""
        templates = self.get_exercise_templates()
        by_title = {x.get("title", "").casefold(): x.get("id") for x in templates}
        equivalents = {
            "dumbbell bench press": ("dumbbell chest press", "chest press", "bench press"),
            "romanian deadlift": ("romanian deadlift", "dumbbell romanian deadlift", "barbell romanian deadlift"),
            "standing calf raise": ("calf raise", "standing calf raise", "calf press"),
            "pallof press": ("pallof press", "cable anti rotation", "anti rotation press"),
            "hollow hold": ("hollow hold", "hollow body hold", "plank"),
            "assisted pull up": ("assisted pull up", "pull up"),
            "inverted row": ("inverted row", "bodyweight row", "row"),
        }
        exported: dict[str, str] = {}
        for session in program["sessions"]:
            exercises = []
            for order, exercise in enumerate(session["exercises"]):
                wanted = exercise["name"].casefold()
                template_id = exercise.get("hevyTemplateId") or by_title.get(wanted) or next((v for k, v in by_title.items() if wanted in k or k in wanted), None)
                if not template_id:
                    aliases = equivalents.get(wanted, (wanted,))
                    template_id = next((value for title, value in by_title.items() if any(alias in title for alias in aliases)), None)
                if not template_id:
                    raise ValueError(f"GoalForge could not find a safe Hevy equivalent for '{exercise['name']}'. Regenerate the plan to use your current Hevy catalog.")
                reps = exercise["reps"]
                numbers = [int(x) for x in __import__("re").findall(r"\d+", reps)]
                is_duration = "sec" in reps.lower()
                routine_set = {"type": "normal", "weight_kg": None, "reps": None if is_duration else (numbers[-1] if numbers else None), "duration_seconds": (numbers[-1] if is_duration and numbers else None), "distance_meters": None, "custom_metric": None, "rep_range": ({"start": numbers[0], "end": numbers[-1]} if not is_duration and len(numbers) >= 2 else None)}
                exercises.append({"exercise_template_id": template_id, "superset_id": None, "rest_seconds": exercise["restSeconds"], "notes": f"{exercise['notes']} Progression: {exercise['progression']}", "sets": [routine_set.copy() for _ in range(exercise["sets"])]})
            focus = session["name"].split("·", 1)[-1].strip()
            block = f"{program.get('blockName', 'Foundation')} B{program.get('blockNumber', 1):02d}"
            week = f"W{program.get('weekNumber', 1):02d}"
            routine = {"title": f"GF · {goal_title} · {block} · {week} · {focus}", "folder_id": None, "notes": f"{program['programName']}\n{session['focus']}\nGenerated by GoalForge AI.", "exercises": exercises}
            existing = existing_ids.get(session["name"])
            response = self.update_routine(existing, routine) if existing else self.create_routine(routine)
            entity = response.get("routine", response)
            exported[session["name"]] = entity.get("id", existing or "")
        return exported

    def close(self) -> None:
        self.client.close()


def _as_utc(value: str | None) -> datetime | None:
    if not value: return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def parse_hevy_workouts(workouts: list[dict], synced_after: str | None) -> tuple[list[dict], dict]:
    """Convert workouts occurring after a goal's cutoff into progress signals."""
    threshold = _as_utc(synced_after)
    new = []
    best_pullups, best_hang = 0, 0
    latest = synced_after
    for workout in workouts:
        # Creation/update timestamps are not achievement timestamps: use when the
        # workout happened so an old workout edited today cannot count toward a new goal.
        stamp = workout.get("start_time") or workout.get("end_time")
        parsed = _as_utc(stamp)
        if threshold and parsed and parsed <= threshold: continue
        new.append(workout)
        if stamp and (not latest or stamp > latest): latest = stamp
        for exercise in workout.get("exercises", []):
            title = exercise.get("title", "").lower()
            for item in exercise.get("sets", []):
                if "pull" in title and "up" in title:
                    best_pullups = max(best_pullups, int(item.get("reps") or 0))
                if "dead hang" in title or ("hang" in title and "dead" in title):
                    best_hang = max(best_hang, int(item.get("duration_seconds") or item.get("duration") or 0))
    return new, {"pull_ups": best_pullups, "dead_hang_seconds": best_hang, "workouts_completed": len(new), "last_sync": latest}
