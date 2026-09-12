import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from .database import Base, engine, get_db, SessionLocal
from .models import CoachFeedback, Competency, Goal, Milestone, ProgressUpdate, User, WorkoutProgram, ReadinessCriterion
from .providers import HevyFitnessProvider
from .competencies import DEFINITIONS
from .schemas import AnalyzeRequest, GoalCreate, ProgressCreate, ReadinessManualUpdate
from .agents import build_initial_graph, build_update_graph, goal_summary_agent, _readiness
from .config import get_settings
from .hevy_sync import sync_goal_from_hevy

Base.metadata.create_all(bind=engine)
app = FastAPI(title="GoalForge AI", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
initial_graph, update_graph = build_initial_graph(), build_update_graph()
_hevy_catalog_cache: dict = {"value": [], "expires_at": datetime.min.replace(tzinfo=timezone.utc)}


async def _hevy_sync_loop() -> None:
    """Imports fresh workouts on a fixed cadence; failures do not stop the API."""
    settings = get_settings()
    while True:
        if settings.hevy_api_key:
            db = SessionLocal()
            try:
                for goal in db.query(Goal).all():
                    try:
                        await asyncio.to_thread(sync_goal_from_hevy, db, goal, update_graph, graph_input, persist_workflow, evaluate_hevy_readiness)
                    except Exception:
                        # A manual sync exposes a useful error; the unattended loop
                        # remains quiet and retries on the next interval.
                        pass
            finally:
                db.close()
        await asyncio.sleep(max(5, settings.hevy_sync_interval_minutes) * 60)


@app.on_event("startup")
async def start_hevy_sync() -> None:
    app.state.hevy_sync_task = asyncio.create_task(_hevy_sync_loop())


@app.on_event("shutdown")
async def stop_hevy_sync() -> None:
    task = getattr(app.state, "hevy_sync_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError): await task


def goal_or_404(db: Session, goal_id: int) -> Goal:
    goal = db.get(Goal, goal_id)
    if not goal: raise HTTPException(404, "Goal not found")
    return goal


def readiness_track_items(goal: Goal) -> list[dict]:
    """The deterministic progression used for readiness, including legacy goals."""
    return _readiness({"goal": {"title": goal.title, "description": goal.description}})["criteria"]


def readiness_goal_type(goal: Goal) -> str:
    text = f"{goal.title} {goal.description}".casefold()
    if "bench" in text: return "bench"
    if any(term in text for term in ("run", "marathon", "5k", "10k")): return "running"
    if any(term in text for term in ("aerial", "hoop", "lyra")): return "aerial"
    return "general"


def ensure_readiness_tracks(db: Session, goal: Goal) -> None:
    """Upgrade the original one-item checklist into safe, sequential tracks.

    Older goals stored one criterion at the final target (for example, a 60s
    hang).  Preserve an earned completion while expanding it into the smaller
    steps, so a goal never needs to be recreated to get progressive readiness.
    """
    criteria = list(goal.readiness_criteria)
    expected_type = readiness_goal_type(goal)
    tracks = {c.evidence.get("track", "") for c in criteria}
    inferred_type = (next((c.evidence.get("goalType") for c in criteria if c.evidence.get("goalType")), None)
                     or ("bench" if "Bench press strength" in tracks else "running" if "Running endurance" in tracks else "aerial" if "Grip & hanging" in tracks else "general"))
    if criteria and all(c.evidence.get("track") for c in criteria) and inferred_type == expected_type:
        return

    # A checklist from a different goal category is not transferable (an
    # aerial technique check must not complete a bench-press technique check).
    legacy_by_metric = {c.metric_type: c for c in criteria if c.metric_type} if inferred_type == expected_type else {}
    manual_technique = next((c for c in criteria if not c.metric_type), None) if inferred_type == expected_type else None
    for criterion in criteria:
        db.delete(criterion)

    for item in readiness_track_items(goal):
        legacy = legacy_by_metric.get(item.get("metricType"))
        completed = bool(legacy and legacy.status == "complete" and (legacy.threshold or 0) >= (item.get("threshold") or 0))
        if item.get("metricType") is None and manual_technique:
            completed = manual_technique.status == "complete"
        evidence = {"track": item["track"], "step": item["step"], "goalType": expected_type}
        source = None
        if completed and legacy:
            source = legacy.completion_source
            evidence = {**evidence, **legacy.evidence}
        db.add(ReadinessCriterion(
            goal_id=goal.id, name=item["name"], target=item["target"],
            metric_type=item.get("metricType"), threshold=item.get("threshold"),
            hevy_exercise=item.get("hevyExercise"), unlocks=item["unlocks"],
            weight=item["weight"], status="complete" if completed else "in_progress",
            completion_source=source, evidence=evidence,
        ))
    db.flush()


def serialize(goal: Goal) -> dict:
    latest_program = goal.workout_programs[-1] if goal.workout_programs else None
    grouped: dict[str, list[ReadinessCriterion]] = {}
    for c in goal.readiness_criteria:
        grouped.setdefault(c.evidence.get("track", "General"), []).append(c)
    criteria = []
    for track, steps in grouped.items():
        steps.sort(key=lambda item: item.evidence.get("step", 1))
        active = next((item for item in steps if item.status != "complete"), None)
        for item in steps:
            index = steps.index(item)
            criteria.append({"id": item.id, "name": item.name, "target": item.target, "unlocks": item.unlocks, "status": item.status, "completionSource": item.completion_source, "evidence": item.evidence, "weight": item.weight, "track": track, "isActive": item.id == (active.id if active else None), "nextTarget": (steps[index + 1].target if item.id == (active.id if active else None) and index + 1 < len(steps) else None)})
    total = sum(c["weight"] for c in criteria)
    percentage = round(100 * sum(c["weight"] for c in criteria if c["status"] == "complete") / total) if total else 0
    evidence = goal.current_abilities.get("competency_evidence", {})
    cards = []
    for c in goal.competencies:
        d, e = DEFINITIONS.get(c.name, {}), evidence.get(c.name, {})
        value, target = e.get("value", 0), e.get("target", d.get("target", 1))
        cards.append({"id": c.id, "name": c.name, "importance": c.importance, "progress": min(100, round(100 * value / target)), "verifiedExercise": e.get("exercise", d.get("exercise")), "currentValue": value, "targetValue": target, "unit": e.get("unit", d.get("unit")), "source": e.get("source")})
    return {"id": goal.id, "title": goal.title, "shortTitle": goal.current_abilities.get("short_summary", goal.title), "description": goal.description, "targetDate": goal.target_date, "assessment": goal.assessment, "gapAnalysis": goal.gap_analysis, "plan": goal.plan, "workoutProgram": ({"id": latest_program.id, **latest_program.payload, "hevyRoutineIds": latest_program.hevy_routine_ids} if latest_program else None), "goalReadiness": {"percentage": percentage, "criteria": criteria}, "achievement": goal.achievement, "agentLog": goal.agent_log, "competencies": cards, "milestones": [{"id": m.id, "title": m.title, "target": m.target, "duePhase": m.due_phase, "completed": m.completed, "status": "Completed" if m.completed else "In progress"} for m in goal.milestones], "progressUpdates": [{"id": p.id, "pullUps": p.pull_ups, "deadHangSeconds": p.dead_hang_seconds, "workoutsCompleted": p.workouts_completed, "notes": p.notes, "createdAt": p.created_at.isoformat()} for p in goal.progress_updates], "coachFeedback": [f.payload for f in goal.coach_feedback]}


def evaluate_hevy_readiness(goal: Goal) -> None:
    """Auto-complete only objective criteria supported by imported Hevy evidence."""
    imports = [p for p in goal.progress_updates if p.notes.startswith("Imported automatically from Hevy")]
    values = {"pull_ups": max([p.pull_ups for p in imports] or [0]), "dead_hang_seconds": max([p.dead_hang_seconds for p in imports] or [0]), "workouts_completed": sum(p.workouts_completed for p in imports), **goal.current_abilities.get("readiness_evidence", {})}
    for criterion in goal.readiness_criteria:
        if criterion.status == "complete" or not criterion.metric_type or criterion.threshold is None: continue
        achieved = values.get(criterion.metric_type, 0)
        if achieved >= criterion.threshold:
            criterion.status, criterion.completion_source = "complete", "hevy"
            criterion.evidence = {**criterion.evidence, "metric": criterion.metric_type, "achievedValue": achieved, "target": criterion.threshold, "provider": "hevy"}


def graph_input(goal: Goal) -> dict:
    catalog = _hevy_catalog_cache["value"]
    if get_settings().hevy_api_key and datetime.now(timezone.utc) >= _hevy_catalog_cache["expires_at"]:
        provider = HevyFitnessProvider(get_settings().hevy_api_key)
        try:
            catalog = [{"id": x["id"], "title": x["title"]} for x in provider.get_exercise_templates()]
            _hevy_catalog_cache["value"] = catalog
            _hevy_catalog_cache["expires_at"] = datetime.now(timezone.utc) + timedelta(hours=6)
        except Exception:
            pass
        finally:
            provider.close()
    return {"goal": {"id": goal.id, "title": goal.title, "description": goal.description, "current_abilities": goal.current_abilities}, "profile": goal.user.profile, "assessment": goal.assessment, "gap_analysis": goal.gap_analysis, "plan": goal.plan, "progress_updates": [{"pull_ups": p.pull_ups, "dead_hang_seconds": p.dead_hang_seconds, "workouts_completed": p.workouts_completed, "notes": p.notes} for p in goal.progress_updates], "competencies": {"requiredCompetencies": [{"name": c.name, "importance": c.importance} for c in goal.competencies]}, "readiness": {"criteria": [{"name": c.name, "target": c.target, "track": c.evidence.get("track", "Goal readiness"), "status": c.status} for c in goal.readiness_criteria]}, "hevy_catalog": catalog, "agent_log": []}


def persist_workflow(db: Session, goal: Goal, result: dict) -> None:
    goal.assessment = result.get("assessment", goal.assessment)
    goal.gap_analysis = result.get("gap_analysis", goal.gap_analysis)
    goal.plan = result.get("plan", goal.plan)
    goal.achievement = result.get("achievement", goal.achievement)
    if result.get("workout_program"):
        db.add(WorkoutProgram(goal_id=goal.id, payload=result["workout_program"]))
    if result.get("readiness") and not goal.readiness_criteria:
        # Keep readiness deterministic: the specialist agent defines the
        # concept, while this canonical progression guarantees individual,
        # sequential milestones in the product.
        for item in readiness_track_items(goal):
            db.add(ReadinessCriterion(goal_id=goal.id, name=item["name"], target=item["target"], metric_type=item.get("metricType"), threshold=item.get("threshold"), hevy_exercise=item.get("hevyExercise"), unlocks=item["unlocks"], weight=item["weight"], evidence={"track": item.get("track", "General"), "step": item.get("step", 1), "goalType": readiness_goal_type(goal)}))
    ensure_readiness_tracks(db, goal)
    goal.agent_log = [*(goal.agent_log or []), *result.get("agent_log", [])][-100:]
    incoming = result.get("competencies", {}).get("requiredCompetencies", [])
    if incoming:
        for old in list(goal.competencies): db.delete(old)
        for item in incoming:
            db.add(Competency(goal_id=goal.id, name=item["name"], importance=item["importance"], progress=goal.achievement.get("competencyProgress", {}).get(item["name"], 0)))
    incoming_milestones = result.get("plan", {}).get("milestones", [])
    if incoming_milestones:
        for old in list(goal.milestones): db.delete(old)
        for item in incoming_milestones:
            db.add(Milestone(goal_id=goal.id, title=item["title"], target=item["target"], due_phase=item["due_phase"], completed=goal.achievement.get("milestoneStatus", {}).get(item["title"]) == "complete"))
    if result.get("coaching"):
        db.add(CoachFeedback(goal_id=goal.id, payload=result["coaching"]))
    db.commit(); db.refresh(goal)


@app.get("/health")
def health(): return {"status": "ok"}


@app.post("/goal", status_code=201)
def create_goal(payload: GoalCreate, db: Session = Depends(get_db)):
    user = User(name=payload.user_profile.get("name", "GoalForge User"), profile=payload.user_profile)
    db.add(user); db.flush()
    summary, _ = goal_summary_agent.invoke({"goal": {"title": payload.title, "description": payload.description}})
    abilities = {**payload.current_abilities, "short_summary": summary["shortTitle"]}
    goal = Goal(user_id=user.id, title=payload.title, description=payload.description, current_abilities=abilities, target_date=payload.target_date)
    db.add(goal); db.commit(); db.refresh(goal)
    return serialize(goal)


@app.post("/goal/analyze")
def analyze_goal(payload: AnalyzeRequest, db: Session = Depends(get_db)):
    goal = goal_or_404(db, payload.goal_id)
    persist_workflow(db, goal, initial_graph.invoke(graph_input(goal)))
    return serialize(goal)


@app.post("/goal/{goal_id}/readiness/{criterion_id}/manual")
def set_manual_readiness(goal_id: int, criterion_id: int, payload: ReadinessManualUpdate, db: Session = Depends(get_db)):
    goal = goal_or_404(db, goal_id)
    ensure_readiness_tracks(db, goal)
    db.commit(); db.refresh(goal)
    criterion = next((c for c in goal.readiness_criteria if c.id == criterion_id), None)
    if not criterion: raise HTTPException(404, "Readiness criterion not found")
    track = sorted((c for c in goal.readiness_criteria if c.evidence.get("track", "General") == criterion.evidence.get("track", "General")), key=lambda c: c.evidence.get("step", 1))
    active = next((c for c in track if c.status != "complete"), None)
    if payload.completed and active and criterion.id != active.id:
        raise HTTPException(409, "Complete the current readiness step before moving to the next one.")
    if not payload.completed:
        # Undo is deliberately stepwise: reverse only the latest achieved item
        # in this track, so a user returns to the immediately previous goal.
        undo_candidate = track[track.index(active) - 1] if active and track.index(active) > 0 else (track[-1] if not active else None)
        if not undo_candidate or criterion.id != undo_candidate.id:
            raise HTTPException(409, "Undo the most recently completed readiness step first.")
    if payload.completed:
        criterion.status, criterion.completion_source = "complete", "manual"
        criterion.evidence = {**criterion.evidence, "provider": "manual", "note": "Marked complete by the user"}
    else:
        criterion.status, criterion.completion_source = "in_progress", None
        criterion.evidence = {"track": criterion.evidence.get("track", "General"), "step": criterion.evidence.get("step", 1), "goalType": criterion.evidence.get("goalType", readiness_goal_type(goal))}
    db.commit(); db.refresh(goal)
    # A manual milestone is meaningful progress: create fresh coaching and an
    # adapted plan just as a Hevy-imported update would.
    persist_workflow(db, goal, update_graph.invoke(graph_input(goal)))
    return serialize(goal)


@app.get("/goal/{goal_id}")
def get_goal(goal_id: int, db: Session = Depends(get_db)):
    goal = goal_or_404(db, goal_id)
    ensure_readiness_tracks(db, goal)
    db.commit(); db.refresh(goal)
    return serialize(goal)


@app.get("/goals")
def get_goals(db: Session = Depends(get_db)):
    """Goal index; production deployments should scope this to the authenticated user."""
    goals = db.query(Goal).order_by(Goal.created_at.desc()).all()
    return [{"id": goal.id, "title": goal.title, "shortTitle": goal.current_abilities.get("short_summary", goal.title), "progress": goal.achievement.get("overallProgress", 0)} for goal in goals]


@app.get("/goal/{goal_id}/roadmap")
def get_roadmap(goal_id: int, db: Session = Depends(get_db)):
    goal = goal_or_404(db, goal_id)
    return {"goalId": goal.id, "roadmap": goal.plan, "milestones": serialize(goal)["milestones"]}


@app.post("/goal/{goal_id}/sync/hevy")
def sync_hevy(goal_id: int, db: Session = Depends(get_db)):
    """On-demand secure import; the key is read from server environment only."""
    goal = goal_or_404(db, goal_id)
    try:
        result = sync_goal_from_hevy(db, goal, update_graph, graph_input, persist_workflow, evaluate_hevy_readiness)
    except ValueError as error:
        raise HTTPException(503, str(error))
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 429:
            raise HTTPException(429, "Hevy rate-limited GoalForge. Wait a few minutes before syncing again; your API key is not the problem.")
        raise HTTPException(502, f"Hevy returned HTTP {error.response.status_code}. Verify the API key and Hevy Pro API access.")
    except httpx.ConnectError:
        raise HTTPException(502, "GoalForge could not reach Hevy. Check this computer's internet/DNS connection and try again.")
    except httpx.TimeoutException:
        raise HTTPException(504, "Hevy did not respond in time. Try syncing again shortly.")
    except Exception as error:
        raise HTTPException(502, f"Hevy sync failed: {type(error).__name__}.")
    return {**result, "goal": serialize(goal)}


@app.post("/goal/{goal_id}/program/export/hevy")
def export_program_to_hevy(goal_id: int, db: Session = Depends(get_db)):
    """Explicitly export the latest reviewed GoalForge block; never runs automatically."""
    goal = goal_or_404(db, goal_id)
    if not goal.workout_programs:
        raise HTTPException(409, "Generate a goal analysis before exporting a program.")
    if not get_settings().hevy_api_key:
        raise HTTPException(503, "Hevy is not configured. Add HEVY_API_KEY to backend/.env and restart the API.")
    program = goal.workout_programs[-1]
    provider = HevyFitnessProvider(get_settings().hevy_api_key)
    try:
        program.hevy_routine_ids = provider.export_program(program.payload, program.hevy_routine_ids or {}, goal.title)
        db.commit(); db.refresh(goal)
    except ValueError as error:
        raise HTTPException(422, str(error))
    except Exception:
        raise HTTPException(502, "Hevy could not export this program. Check your key and exercise templates.")
    finally:
        provider.close()
    return {"message": "Workout routines exported to Hevy.", "goal": serialize(goal)}


@app.post("/goal/{goal_id}/program/generate")
def generate_workout_program(goal_id: int, db: Session = Depends(get_db)):
    """Create a fresh workout block for goals made before workout programming existed."""
    goal = goal_or_404(db, goal_id)
    persist_workflow(db, goal, update_graph.invoke(graph_input(goal)))
    return {"message": "A fresh workout block is ready for review.", "goal": serialize(goal)}
