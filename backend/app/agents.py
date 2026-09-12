"""Independent GoalForge agents. Each agent owns a prompt, schema, memory, and callable."""
from __future__ import annotations
from datetime import datetime, timezone
import re
from typing import Any, Callable
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict
from .config import get_settings


class AssessmentOutput(BaseModel):
    fitnessLevel: str
    constraints: list[str]
    availableTime: str
    baselineMetrics: dict[str, Any]


class GoalSummaryOutput(BaseModel):
    shortTitle: str = Field(max_length=48)


class CompetencyItem(BaseModel):
    name: str
    importance: int = Field(ge=1, le=10)


class CompetencyOutput(BaseModel):
    requiredCompetencies: list[CompetencyItem]


class GapOutput(BaseModel):
    skillGaps: list[str]
    riskAreas: list[str]
    priorityOrder: list[str]


class MilestoneItem(BaseModel):
    title: str
    target: str
    due_phase: str


class PlanningOutput(BaseModel):
    milestones: list[MilestoneItem]
    trainingPlan: list[str]
    timeline: list[dict[str, str]]


class CoachingOutput(BaseModel):
    coachInsights: list[str]
    adjustments: list[str]
    nextSteps: list[str]


class WorkoutExercise(BaseModel):
    name: str
    hevyTemplateId: str | None = None
    sets: int = Field(ge=1, le=8)
    reps: str
    restSeconds: int = Field(ge=30, le=300)
    notes: str
    progression: str


class WorkoutSession(BaseModel):
    name: str
    focus: str
    durationMinutes: int = Field(ge=50, le=75)
    warmup: list[str]
    exercises: list[WorkoutExercise]
    cooldown: list[str]


class WorkoutProgramOutput(BaseModel):
    programName: str
    durationWeeks: int = Field(ge=1, le=8)
    blockName: str = "Foundation"
    blockNumber: int = Field(default=1, ge=1)
    weekNumber: int = Field(default=1, ge=1, le=8)
    sessions: list[WorkoutSession]
    progressionRules: list[str]
    safetyNotes: list[str]


class ReadinessItem(BaseModel):
    name: str
    target: str
    metricType: str | None = None
    threshold: float | None = None
    hevyExercise: str | None = None
    unlocks: str
    weight: int = Field(ge=1, le=10)
    track: str = "General"
    step: int = 1


class ReadinessOutput(BaseModel):
    criteria: list[ReadinessItem]


class AchievementOutput(BaseModel):
    overallProgress: int = Field(ge=0, le=100)
    competencyProgress: dict[str, int]
    milestoneStatus: dict[str, str]


class GraphState(TypedDict, total=False):
    hevy_catalog: list[dict[str, str]]
    goal: dict[str, Any]
    profile: dict[str, Any]
    progress_updates: list[dict[str, Any]]
    assessment: dict[str, Any]
    competencies: dict[str, Any]
    gap_analysis: dict[str, Any]
    plan: dict[str, Any]
    coaching: dict[str, Any]
    workout_program: dict[str, Any]
    readiness: dict[str, Any]
    achievement: dict[str, Any]
    agent_log: list[dict[str, Any]]
    agent_memory: dict[str, list[dict[str, Any]]]


class Agent:
    """A real agent boundary: dedicated instruction, validated output, and retained local memory."""
    def __init__(self, name: str, prompt: str, schema: type[BaseModel], fallback: Callable[[GraphState], dict]):
        self.name, self.system_prompt, self.schema, self.fallback = name, prompt, schema, fallback
        self.memory: list[dict[str, Any]] = []

    def invoke(self, state: GraphState) -> dict[str, Any]:
        output: BaseModel
        settings = get_settings()
        if settings.openai_api_key:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0.2)
            prompt = (f"{self.system_prompt}\nReturn only data matching the supplied JSON schema. "
                      f"Context: {state}")
            output = llm.with_structured_output(self.schema).invoke(prompt)
        else:
            output = self.schema.model_validate(self.fallback(state))
        payload = output.model_dump()
        event = {"agent": self.name, "timestamp": datetime.now(timezone.utc).isoformat(), "output": payload}
        self.memory.append(event)
        return payload, event


def _assessment(s: GraphState) -> dict:
    a = s.get("goal", {}).get("current_abilities", {})
    return {"fitnessLevel": "beginner" if not a.get("pull_ups") else "developing", "constraints": a.get("constraints", []), "availableTime": a.get("available_time", "3 sessions per week"), "baselineMetrics": a}


def _goal_summary(s: GraphState) -> dict:
    title = s.get("goal", {}).get("title", "My goal").strip()
    return {"shortTitle": " ".join(title.split()[:6])[:48]}


def _competencies(s: GraphState) -> dict:
    return {"requiredCompetencies": [{"name": n, "importance": i} for n, i in [("Pulling Strength", 10), ("Grip Strength", 9), ("Core Strength", 9), ("Mobility", 7), ("Endurance", 6)]]}


def _gap(s: GraphState) -> dict:
    names = [x["name"] for x in s["competencies"]["requiredCompetencies"]]
    return {"skillGaps": names, "riskAreas": ["Avoid rapid load increases", "Prioritize shoulder preparation"], "priorityOrder": names}


def _plan(s: GraphState) -> dict:
    changed = bool(s.get("coaching"))
    suffix = " adjusted after your latest check-in" if changed else ""
    return {"milestones": [
        {"title": "Build a training base", "target": "3 consistent sessions per week", "due_phase": "Months 1–2"},
        {"title": "Develop pulling strength", "target": "5 controlled assisted pull-ups", "due_phase": "Months 3–5"},
        {"title": "Performance readiness", "target": "Complete a full practice routine", "due_phase": "Months 6–9"}],
        "trainingPlan": ["Two full-body strength sessions weekly", "One skills and mobility session weekly" + suffix, "Log recovery and pain after each session"],
        "timeline": [{"phase": "Foundation", "duration": "Months 1–2", "focus": "Consistency and joint preparation"}, {"phase": "Build", "duration": "Months 3–5", "focus": "Strength and skill progressions"}, {"phase": "Perform", "duration": "Months 6–9", "focus": "Routine practice"}]}


def _coaching(s: GraphState) -> dict:
    updates = s.get("progress_updates") or []
    total_workouts = sum(item.get("workouts_completed", 0) for item in updates)
    best_pullups = max([item.get("pull_ups", 0) for item in updates] or [0])
    best_hang = max([item.get("dead_hang_seconds", 0) for item in updates] or [0])
    readiness = (s.get("readiness") or {}).get("criteria", [])
    active = []
    seen_tracks = set()
    for item in readiness:
        track = item.get("track", "Goal readiness")
        if track not in seen_tracks and item.get("status") != "complete":
            active.append(f"{item.get('name')}: {item.get('target')}")
            seen_tracks.add(track)
    evidence = s.get("goal", {}).get("current_abilities", {}).get("readiness_evidence", {})
    performance = []
    if best_pullups: performance.append(f"{best_pullups} pull-up{'s' if best_pullups != 1 else ''}")
    if best_hang: performance.append(f"a {best_hang}-second dead hang")
    for metric, value in evidence.items():
        if metric == "bench_press_lb" and value: performance.append(f"a {round(value)} lb bench press")
    snapshot = ", ".join(performance) if performance else "no completed performance test has been captured yet"
    focus = "; ".join(active[:2]) if active else "maintain your current routine and re-test your key movement"
    return {
        "coachInsights": [
            f"Progress rundown: you have logged {total_workouts} workout{'s' if total_workouts != 1 else ''} toward {s.get('goal', {}).get('title', 'this goal')}. Your recorded performance is {snapshot}.",
            f"What to improve next: focus on {focus}. Build gradually and prioritize clean, repeatable reps over rushing the next milestone.",
            "You are building the capacity this goal requires one session at a time. Consistency is real progress—even before the final milestone is visible.",
        ],
        "adjustments": ["Keep the next sessions targeted to the active readiness steps; add load or volume only after controlled form is consistent."],
        "nextSteps": [f"Complete or log evidence for: {active[0]}" if active else "Schedule your next goal-specific session", "Review recovery before your next hard session"],
    }


def _workout_program(s: GraphState) -> dict:
    return {"programName": "Foundation Strength · Weeks 1–4", "durationWeeks": 4, "blockName": "Foundation", "blockNumber": 1, "weekNumber": 1,
      "sessions": [
        {"name": "Session A · Pull & Core", "focus": "Pulling strength, grip, scapular control, and trunk control", "durationMinutes": 60, "warmup": ["5 minutes easy cardio", "Band pull-aparts: 2 × 15", "Scapular pull-ups: 2 × 8"], "exercises": [
          {"name": "Lat Pulldown", "sets": 3, "reps": "8-12", "restSeconds": 120, "notes": "Use a load that leaves 2 reps in reserve.", "progression": "Add weight after all sets reach 12 clean reps."},
          {"name": "Dumbbell Row", "sets": 3, "reps": "8-12", "restSeconds": 90, "notes": "Pull elbow toward hip and avoid twisting.", "progression": "Add load after 3 × 12 clean reps."},
          {"name": "Dead Hang", "sets": 3, "reps": "20-30 sec", "restSeconds": 90, "notes": "Keep shoulders active; stop for pain.", "progression": "Add 5 seconds when all holds are solid."},
          {"name": "Face Pull", "sets": 3, "reps": "12-15", "restSeconds": 60, "notes": "Move slowly with ribs down.", "progression": "Add load after 3 × 15."},
          {"name": "Hanging Knee Raise", "sets": 3, "reps": "8-10", "restSeconds": 60, "notes": "Avoid swinging; regress to captain's chair if needed.", "progression": "Add reps until 3 × 10."},
          {"name": "Plank", "sets": 3, "reps": "30-45 sec", "restSeconds": 60, "notes": "Maintain a neutral spine.", "progression": "Add 5 seconds per week."}], "cooldown": ["Lat stretch: 2 × 30 seconds", "Thoracic rotation: 1 minute each side"]},
        {"name": "Session B · Full Body", "focus": "Foundational lower body, pushing balance, and shoulder resilience", "durationMinutes": 60, "warmup": ["5 minutes easy cardio", "Bodyweight squats: 2 × 10", "Shoulder circles and band external rotation: 2 × 12"], "exercises": [
          {"name": "Goblet Squat", "sets": 3, "reps": "8-12", "restSeconds": 90, "notes": "Controlled depth and braced torso.", "progression": "Increase load only after all sets reach 12."},
          {"name": "Romanian Deadlift", "sets": 3, "reps": "8-10", "restSeconds": 120, "notes": "Keep lats tight and hinge at the hips.", "progression": "Add load after 3 × 10."},
          {"name": "Dumbbell Bench Press", "sets": 3, "reps": "8-12", "restSeconds": 90, "notes": "Use a controlled range and neutral wrists.", "progression": "Add load after 3 × 12."},
          {"name": "Dumbbell Row", "sets": 3, "reps": "8-12", "restSeconds": 90, "notes": "Pull elbow toward hip.", "progression": "Add load after 3×12 with clean form."},
          {"name": "Standing Calf Raise", "sets": 3, "reps": "12-15", "restSeconds": 60, "notes": "Use a full controlled range.", "progression": "Add load after 3 × 15."},
          {"name": "Pallof Press", "sets": 3, "reps": "10-12", "restSeconds": 60, "notes": "Resist rotation throughout.", "progression": "Add reps then load."}], "cooldown": ["Hip flexor stretch: 2 × 30 seconds", "Chest doorway stretch: 2 × 30 seconds"]},
        {"name": "Session C · Skills & Mobility", "focus": "Aerial-specific pulling practice, mobility, and recovery", "durationMinutes": 60, "warmup": ["5 minutes easy cardio", "Wrist circles and shoulder CARs: 2 minutes", "Band-assisted scapular pulls: 2 × 10"], "exercises": [
          {"name": "Assisted Pull Up", "sets": 3, "reps": "5-8", "restSeconds": 120, "notes": "Use enough assistance for smooth reps.", "progression": "Reduce assistance after 3×8."},
          {"name": "Inverted Row", "sets": 3, "reps": "8-12", "restSeconds": 90, "notes": "Keep body rigid and pull chest to bar.", "progression": "Lower the bar when 3 × 12 is easy."},
          {"name": "Dead Hang", "sets": 3, "reps": "20-30 sec", "restSeconds": 90, "notes": "Keep the effort submaximal.", "progression": "Add 5 seconds when comfortable."},
          {"name": "Hollow Hold", "sets": 3, "reps": "20-30 sec", "restSeconds": 60, "notes": "Keep lower back gently pressed down.", "progression": "Add 5 seconds per week."},
          {"name": "Glute Bridge", "sets": 3, "reps": "12-15", "restSeconds": 60, "notes": "Keep ribs down and squeeze at the top.", "progression": "Add load after 3 × 15."},
          {"name": "Face Pull", "sets": 3, "reps": "12-15", "restSeconds": 60, "notes": "Finish with shoulder-friendly control.", "progression": "Add load after 3 × 15."}], "cooldown": ["Passive lat stretch: 2 × 30 seconds", "Shoulder flexion stretch: 2 × 30 seconds", "Breathing reset: 2 minutes"]}],
      "progressionRules": ["Keep 1–2 reps in reserve on strength work.", "When a rep range is completed with good form, progress one variable only.", "Reduce volume by 30% if recovery or soreness is unusually poor."],
      "safetyNotes": ["Stop for sharp pain, numbness, or joint instability.", "This is general fitness guidance, not medical advice."]}


def _readiness(s: GraphState) -> dict:
    goal_text = f"{s.get('goal', {}).get('title', '')} {s.get('goal', {}).get('description', '')}".casefold()
    # Goal-specific fallback for when an LLM is unavailable. These tracks are
    # intentionally progressive rather than copying the aerial template.
    if "bench" in goal_text:
        target_match = re.search(r"\b(\d{2,3})\s*(?:lb|lbs|pounds?)\b", goal_text)
        target = int(target_match.group(1)) if target_match else 300
        steps = tuple(max(45, round(target * ratio / 5) * 5) for ratio in (.50, .65, .80, 1.0))
        return {"criteria": [
            *[{"name": "Barbell bench press", "target": f"{weight} lb for 1 controlled rep", "metricType": "bench_press_lb", "threshold": weight, "hevyExercise": "Barbell Bench Press", "unlocks": "The next pressing-strength progression.", "weight": 1, "track": "Bench press strength", "step": index} for index, weight in enumerate(steps, 1)],
            *[{"name": "Training consistency", "target": f"{count} logged workouts", "metricType": "workouts_completed", "threshold": count, "hevyExercise": None, "unlocks": "The next training-volume progression.", "weight": 1, "track": "Training consistency", "step": index} for index, count in enumerate((6, 12, 18), 1)],
            {"name": "Pressing technique check", "target": "Consistent bar path, stable shoulders, and controlled pauses", "metricType": None, "threshold": None, "hevyExercise": None, "unlocks": "A safe attempt at the next bench milestone.", "weight": 2, "track": "Technique", "step": 1},
        ]}
    if any(term in goal_text for term in ("run", "marathon", "5k", "10k")):
        return {"criteria": [
            *[{"name": "Continuous run", "target": f"{minutes} minutes", "metricType": "run_minutes", "threshold": minutes, "hevyExercise": None, "unlocks": "The next endurance progression.", "weight": 1, "track": "Running endurance", "step": index} for index, minutes in enumerate((20, 35, 50, 70), 1)],
            *[{"name": "Training consistency", "target": f"{count} logged workouts", "metricType": "workouts_completed", "threshold": count, "hevyExercise": None, "unlocks": "The next training-volume progression.", "weight": 1, "track": "Training consistency", "step": index} for index, count in enumerate((6, 12, 18), 1)],
        ]}
    if not any(term in goal_text for term in ("aerial", "hoop", "lyra")):
        return {"criteria": [
            *[{"name": "Goal-specific practice", "target": f"{count} focused practice sessions", "metricType": "workouts_completed", "threshold": count, "hevyExercise": None, "unlocks": "The next phase of consistent work toward this goal.", "weight": 1, "track": "Goal practice", "step": index} for index, count in enumerate((3, 6, 12), 1)],
            *[{"name": "Supporting training", "target": f"{count} logged workouts", "metricType": "workouts_completed", "threshold": count + 3, "hevyExercise": None, "unlocks": "More capacity to progress the primary skill safely.", "weight": 1, "track": "Training consistency", "step": index} for index, count in enumerate((3, 6, 9), 1)],
            {"name": "Goal technique check", "target": "Demonstrate the current phase with controlled form", "metricType": None, "threshold": None, "hevyExercise": None, "unlocks": "The next goal-specific practice progression.", "weight": 2, "track": "Technique", "step": 1},
        ]}
    return {"criteria": [
        *[{"name": "Active dead hang", "target": f"{seconds} seconds", "metricType": "dead_hang_seconds", "threshold": seconds, "hevyExercise": "Dead Hang", "unlocks": "The next grip-and-suspension progression.", "weight": 1, "track": "Grip & hanging", "step": index} for index, seconds in enumerate((15, 30, 45, 60), 1)],
        *[{"name": "Controlled pull-ups", "target": f"{reps} clean rep{'s' if reps > 1 else ''}", "metricType": "pull_ups", "threshold": reps, "hevyExercise": "Pull Up", "unlocks": "The next pulling-strength progression.", "weight": 1, "track": "Pulling strength", "step": index} for index, reps in enumerate((1, 2, 3), 1)],
        *[{"name": "Training consistency", "target": f"{count} logged workouts", "metricType": "workouts_completed", "threshold": count, "hevyExercise": None, "unlocks": "The next training-volume progression.", "weight": 1, "track": "Training consistency", "step": index} for index, count in enumerate((3, 6, 9, 12), 1)],
        {"name": "Routine technique check", "target": "Coach-approved 60–90 second beginner sequence", "metricType": None, "threshold": None, "hevyExercise": None, "unlocks": "A full routine rehearsal and performance preparation.", "weight": 2, "track": "Technique", "step": 1}]}


def _achievement(s: GraphState) -> dict:
    updates = s.get("progress_updates", [])
    workouts = sum(x.get("workouts_completed", 0) for x in updates)
    pullups = max([x.get("pull_ups", 0) for x in updates] or [0])
    hang = max([x.get("dead_hang_seconds", 0) for x in updates] or [0])
    readiness = (s.get("readiness") or {}).get("criteria", [])
    if readiness:
        total_weight = sum(item.get("weight", 1) for item in readiness)
        completed_weight = sum(item.get("weight", 1) for item in readiness if item.get("status") == "complete")
        progress = round(100 * completed_weight / total_weight) if total_weight else 0
    else:
        progress = min(100, round(workouts * 3 + pullups * 7 + hang / 10))
    competencies = s.get("competencies", {}).get("requiredCompetencies", [])
    evidence = s.get("goal", {}).get("current_abilities", {}).get("competency_evidence", {})
    cp = {x["name"]: min(100, round(100 * evidence.get(x["name"], {}).get("value", 0) / evidence.get(x["name"], {}).get("target", 1))) for x in competencies}
    milestones = s.get("plan", {}).get("milestones", [])
    thresholds = [round(100 * (index + 1) / max(1, len(milestones))) for index in range(len(milestones))]
    statuses = {milestone["title"]: ("complete" if progress >= thresholds[index] else "in progress") for index, milestone in enumerate(milestones)}
    return {"overallProgress": progress, "competencyProgress": cp, "milestoneStatus": statuses}


assessment_agent = Agent("Assessment Agent", "You assess the user's starting point cautiously. Identify realistic constraints and preserve user-provided metrics.", AssessmentOutput, _assessment)
goal_summary_agent = Agent("Goal Summary Agent", "Create a short, specific, meaningful sidebar label for this goal. Use no more than six words, retain the outcome, and omit filler.", GoalSummaryOutput, _goal_summary)
skill_mapping_agent = Agent("Skill Mapping Agent", "You map a goal into measurable competencies and rank importance from 1 to 10.", CompetencyOutput, _competencies)
gap_agent = Agent("Gap Analysis Agent", "You compare assessment and competencies. Surface practical gaps and injury or sustainability risks.", GapOutput, _gap)
planning_agent = Agent("Planning Agent", "You create a safe milestone roadmap with phased, actionable training. Incorporate coach feedback when present.", PlanningOutput, _plan)
coaching_agent = Agent("Coaching Agent", "Provide a substantive, warm coaching check-in for THIS goal. Return: (1) a concise progress rundown grounded in recorded workouts, readiness, and performance data; (2) exactly what to adjust or prioritize next to improve; (3) concrete next steps; and (4) realistic encouragement. Never merely report a workout count, invent progress, or diagnose medical issues.", CoachingOutput, _coaching)
workout_programming_agent = Agent("Workout Programming Agent", "You turn the current plan into a conservative 1–4 week workout block. Every session must be a complete 60-minute workout. Include a concise blockName, sequential blockNumber, and weekNumber for clear routine exports. The context includes a Hevy exercise catalog: select ONLY exact titles from that catalog and include the matching hevyTemplateId on each exercise. Never prescribe around pain or medical conditions.", WorkoutProgramOutput, _workout_program)
goal_readiness_agent = Agent("Goal Readiness Agent", "You translate THIS goal into a short, safety-conscious readiness checklist. Never reuse an aerial, running, or strength template when it does not match the stated outcome. Create 2–4 goal-specific tracks. Every measurable track must contain 3–4 strictly increasing sequential steps, each with a matching metricType and Hevy exercise when possible. Include what each step unlocks next.", ReadinessOutput, _readiness)
achievement_agent = Agent("Achievement Agent", "You calculate conservative, transparent progress from competencies, milestones and recorded updates.", AchievementOutput, _achievement)


def _node(agent: Agent, field: str):
    def run(state: GraphState):
        payload, event = agent.invoke(state)
        if agent.name == "Workout Programming Agent" and state.get("hevy_catalog"):
            catalog = state["hevy_catalog"]
            by_title = {item["title"].casefold(): item for item in catalog}
            aliases = {"dumbbell bench press": ("dumbbell chest press", "chest press", "bench press"), "standing calf raise": ("calf raise",), "pallof press": ("anti rotation", "pallof"), "hollow hold": ("hollow", "plank"), "assisted pull up": ("assisted pull", "pull up"), "inverted row": ("inverted row", "bodyweight row")}
            for session in payload["sessions"]:
                for exercise in session["exercises"]:
                    key = exercise["name"].casefold()
                    match = by_title.get(key) or next((item for title, item in by_title.items() if key in title or title in key), None)
                    if not match:
                        match = next((item for title, item in by_title.items() if any(alias in title for alias in aliases.get(key, (key,)))), None)
                    if match:
                        exercise["name"], exercise["hevyTemplateId"] = match["title"], match["id"]
            event["output"] = payload
        memory = dict(state.get("agent_memory", {}))
        memory[agent.name] = agent.memory[-10:]
        return {field: payload, "agent_log": [*state.get("agent_log", []), event], "agent_memory": memory}
    return run


def build_initial_graph():
    graph = StateGraph(GraphState)
    graph.add_node("assessment", _node(assessment_agent, "assessment"))
    graph.add_node("competencies", _node(skill_mapping_agent, "competencies"))
    graph.add_node("gap_analysis", _node(gap_agent, "gap_analysis"))
    graph.add_node("planning", _node(planning_agent, "plan"))
    graph.add_node("workout_programming", _node(workout_programming_agent, "workout_program"))
    graph.add_node("goal_readiness", _node(goal_readiness_agent, "readiness"))
    graph.add_node("achievement", _node(achievement_agent, "achievement"))
    graph.add_edge(START, "assessment"); graph.add_edge("assessment", "competencies"); graph.add_edge("competencies", "gap_analysis"); graph.add_edge("gap_analysis", "planning"); graph.add_edge("planning", "workout_programming"); graph.add_edge("workout_programming", "goal_readiness"); graph.add_edge("goal_readiness", "achievement"); graph.add_edge("achievement", END)
    return graph.compile()


def build_update_graph():
    graph = StateGraph(GraphState)
    graph.add_node("achievement_before_coaching", _node(achievement_agent, "achievement"))
    graph.add_node("coaching", _node(coaching_agent, "coaching"))
    graph.add_node("planning", _node(planning_agent, "plan"))
    graph.add_node("workout_programming", _node(workout_programming_agent, "workout_program"))
    graph.add_node("goal_readiness", _node(goal_readiness_agent, "readiness"))
    graph.add_node("achievement", _node(achievement_agent, "achievement"))
    graph.add_edge(START, "achievement_before_coaching"); graph.add_edge("achievement_before_coaching", "coaching"); graph.add_edge("coaching", "planning"); graph.add_edge("planning", "workout_programming"); graph.add_edge("workout_programming", "goal_readiness"); graph.add_edge("goal_readiness", "achievement"); graph.add_edge("achievement", END)
    return graph.compile()
