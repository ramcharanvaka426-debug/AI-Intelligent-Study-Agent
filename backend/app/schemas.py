from datetime import date

import re

from pydantic import BaseModel, Field, field_validator, model_validator


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Enter your full name.")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address.")
        return normalized

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address.")
        return normalized


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
