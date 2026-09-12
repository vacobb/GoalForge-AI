from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="GoalForge User")
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    goals: Mapped[list["Goal"]] = relationship(back_populates="user")


class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    current_abilities: Mapped[dict] = mapped_column(JSON, default=dict)
    target_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    assessment: Mapped[dict] = mapped_column(JSON, default=dict)
    gap_analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    achievement: Mapped[dict] = mapped_column(JSON, default=dict)
    agent_log: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[User] = relationship(back_populates="goals")
    competencies: Mapped[list["Competency"]] = relationship(back_populates="goal", cascade="all, delete-orphan")
    milestones: Mapped[list["Milestone"]] = relationship(back_populates="goal", cascade="all, delete-orphan")
    progress_updates: Mapped[list["ProgressUpdate"]] = relationship(back_populates="goal", cascade="all, delete-orphan")
    coach_feedback: Mapped[list["CoachFeedback"]] = relationship(back_populates="goal", cascade="all, delete-orphan")
    workout_programs: Mapped[list["WorkoutProgram"]] = relationship(back_populates="goal", cascade="all, delete-orphan")
    readiness_criteria: Mapped[list["ReadinessCriterion"]] = relationship(back_populates="goal", cascade="all, delete-orphan")


class Competency(Base):
    __tablename__ = "competencies"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"))
    name: Mapped[str] = mapped_column(String(120))
    importance: Mapped[int] = mapped_column(Integer)
    progress: Mapped[float] = mapped_column(Float, default=0)
    goal: Mapped[Goal] = relationship(back_populates="competencies")


class Milestone(Base):
    __tablename__ = "milestones"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"))
    title: Mapped[str] = mapped_column(String(255))
    target: Mapped[str] = mapped_column(Text)
    due_phase: Mapped[str] = mapped_column(String(80))
    completed: Mapped[bool] = mapped_column(default=False)
    goal: Mapped[Goal] = relationship(back_populates="milestones")


class ProgressUpdate(Base):
    __tablename__ = "progress_updates"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"))
    pull_ups: Mapped[int] = mapped_column(Integer, default=0)
    dead_hang_seconds: Mapped[int] = mapped_column(Integer, default=0)
    workouts_completed: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    goal: Mapped[Goal] = relationship(back_populates="progress_updates")


class CoachFeedback(Base):
    __tablename__ = "coach_feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    goal: Mapped[Goal] = relationship(back_populates="coach_feedback")


class WorkoutProgram(Base):
    __tablename__ = "workout_programs"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"))
    payload: Mapped[dict] = mapped_column(JSON)
    hevy_routine_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    goal: Mapped[Goal] = relationship(back_populates="workout_programs")


class ReadinessCriterion(Base):
    __tablename__ = "readiness_criteria"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"))
    name: Mapped[str] = mapped_column(String(255))
    target: Mapped[str] = mapped_column(String(255))
    metric_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    hevy_exercise: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unlocks: Mapped[str] = mapped_column(Text)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="in_progress")
    completion_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    goal: Mapped[Goal] = relationship(back_populates="readiness_criteria")
