from datetime import date

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    due_date: date
    category: str = Field(default="Study", max_length=40)


class TaskUpdate(BaseModel):
    completed: bool


class TutorRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    course: str = Field(default="General", max_length=80)


class PlannerRequest(BaseModel):
    subjects: list[str] = Field(min_length=1)
    hours_per_day: int = Field(default=2, ge=1, le=8)
    exam_date: date | None = None


class ExamCreate(BaseModel):
    course: str = Field(min_length=2, max_length=80)
    title: str = Field(min_length=2, max_length=120)
    exam_date: date


class QuizRequest(BaseModel):
    topic: str | None = Field(default=None, min_length=2, max_length=160)
    material_id: int | None = Field(default=None, gt=0)
    count: int = Field(default=5, ge=3, le=10)


class QuizScoreCreate(BaseModel):
    topic: str = Field(min_length=2, max_length=160)
    correct: int = Field(ge=0)
    total: int = Field(ge=1, le=10)
