from pydantic import BaseModel, Field
from typing import Any


class GoalCreate(BaseModel):
    title: str
    description: str
    current_abilities: dict[str, Any] = Field(default_factory=dict)
    user_profile: dict[str, Any] = Field(default_factory=dict)
    target_date: str | None = None


class AnalyzeRequest(BaseModel):
    goal_id: int


class ProgressCreate(BaseModel):
    goal_id: int
    pull_ups: int = Field(default=0, ge=0)
    dead_hang_seconds: int = Field(default=0, ge=0)
    workouts_completed: int = Field(default=0, ge=0)
    notes: str = ""


class ReadinessManualUpdate(BaseModel):
    completed: bool
