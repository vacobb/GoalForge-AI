"""Application service that imports Hevy data and invokes the adaptive agent graph."""
from sqlalchemy.orm import Session
from .config import get_settings
from .models import Goal, ProgressUpdate
from .providers import HevyFitnessProvider, parse_hevy_workouts
from .competencies import extract_evidence


def _readiness_evidence(goal: Goal, workouts: list[dict]) -> dict[str, float]:
    """Extract the exact Hevy measurements required by this goal's tracks."""
    evidence = dict((goal.current_abilities or {}).get("readiness_evidence", {}))
    for criterion in goal.readiness_criteria:
        if not criterion.metric_type or not criterion.hevy_exercise:
            continue
        value = float(evidence.get(criterion.metric_type, 0))
        wanted = criterion.hevy_exercise.casefold()
        for workout in workouts:
            for exercise in workout.get("exercises", []):
                if wanted not in exercise.get("title", "").casefold():
                    continue
                for item in exercise.get("sets", []):
                    if criterion.metric_type.endswith("_lb"):
                        measured = float(item.get("weight_kg") or 0) * 2.20462
                    elif criterion.metric_type.endswith("seconds"):
                        measured = float(item.get("duration_seconds") or item.get("duration") or 0)
                    else:
                        measured = float(item.get("reps") or 0)
                    value = max(value, measured)
        evidence[criterion.metric_type] = value
    return evidence


def _apply_goal_start_scope(db: Session, goal: Goal) -> bool:
    """One-time migration from the old all-history importer to goal-scoped sync."""
    abilities = dict(goal.current_abilities or {})
    if abilities.get("hevy_sync_scope_version") == 2:
        return False
    # Only remove system-authored imports. Manual check-ins remain intact.
    for update in list(goal.progress_updates):
        if update.notes.startswith("Imported automatically from Hevy"):
            db.delete(update)
    abilities["hevy_last_sync"] = goal.created_at.isoformat()
    abilities["hevy_sync_scope_version"] = 2
    goal.current_abilities = abilities
    db.commit(); db.refresh(goal)
    return True


def sync_goal_from_hevy(db: Session, goal: Goal, update_graph, graph_input, persist_workflow, evaluate_readiness=None) -> dict:
    settings = get_settings()
    if not settings.hevy_api_key:
        raise ValueError("Hevy is not configured. Add HEVY_API_KEY to backend/.env and restart the API.")
    reset_old_history = _apply_goal_start_scope(db, goal)
    abilities = dict(goal.current_abilities or {})
    provider = HevyFitnessProvider(settings.hevy_api_key)
    try:
        event_since = abilities.get("hevy_event_sync") or abilities.get("hevy_last_sync") or goal.created_at.isoformat()
        workouts, event_checkpoint = provider.get_workout_changes(event_since)
    finally:
        provider.close()
    # Event time determines what changed; workout start time still enforces the
    # user's rule that pre-goal workouts never count toward this goal.
    imported, metrics = parse_hevy_workouts(workouts, goal.created_at.isoformat())
    if not imported:
        if reset_old_history:
            persist_workflow(db, goal, update_graph.invoke(graph_input(goal)))
            return {"importedWorkouts": 0, "message": "Historical Hevy imports were removed. Only workouts after this goal was created will count."}
        # A user-triggered sync is also a request for a fresh assessment. This
        # keeps the coach feed responsive even if Hevy has no newly importable row.
        persist_workflow(db, goal, update_graph.invoke(graph_input(goal)))
        return {"importedWorkouts": 0, "message": "Hevy is already in sync; coaching was refreshed from your latest data."}
    ids = ",".join(str(x.get("id", "unknown")) for x in imported[:8])
    db.add(ProgressUpdate(goal_id=goal.id, pull_ups=metrics["pull_ups"], dead_hang_seconds=metrics["dead_hang_seconds"], workouts_completed=metrics["workouts_completed"], notes=f"Imported automatically from Hevy ({len(imported)} workouts; ids: {ids})."))
    abilities["hevy_last_sync"] = metrics["last_sync"]
    abilities["hevy_event_sync"] = event_checkpoint
    abilities["competency_evidence"] = extract_evidence(imported, abilities.get("competency_evidence", {}))
    abilities["readiness_evidence"] = _readiness_evidence(goal, imported)
    goal.current_abilities = abilities
    db.commit(); db.refresh(goal)
    if evaluate_readiness:
        evaluate_readiness(goal)
        db.commit(); db.refresh(goal)
    persist_workflow(db, goal, update_graph.invoke(graph_input(goal)))
    return {"importedWorkouts": len(imported), "pullUps": metrics["pull_ups"], "deadHangSeconds": metrics["dead_hang_seconds"], "message": "Hevy data imported and your plan was adapted."}
