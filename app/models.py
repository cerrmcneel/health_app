"""Pydantic request/response models."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Confidence = Literal["low", "medium", "high"]
MealType = Literal["breakfast", "lunch", "dinner", "snack", "other"]
Pose = Literal["front", "profile", "back"]


class TextAnalysisIn(BaseModel):
    text: str = Field(min_length=2, max_length=2000)
    model: str | None = None


class MealItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    grams: float = Field(default=0, ge=0, le=10000)
    calories: float = Field(default=0, ge=0, le=20000)
    protein_g: float = Field(default=0, ge=0, le=2000)
    carbs_g: float = Field(default=0, ge=0, le=2000)
    fat_g: float = Field(default=0, ge=0, le=2000)
    confidence: Confidence = "medium"


class MealIn(BaseModel):
    """A meal as confirmed by the user, after editing the model's estimate."""
    name: str = Field(default="Meal", max_length=160)
    meal_type: MealType = "other"
    items: list[MealItemIn] = Field(min_length=1)
    day: date | None = None          # defaults to today in the configured TZ
    source: Literal["photo", "manual", "text"] = "manual"
    notes: str = Field(default="", max_length=500)
    pending_image: str | None = None  # token from POST /api/analyze
    model: str | None = None
    raw_json: str | None = None

    @field_validator("name")
    @classmethod
    def _default_name(cls, v: str) -> str:
        return v.strip() or "Meal"


class MealUpdate(BaseModel):
    """Partial update. Supplying `items` replaces the whole item list."""
    name: str | None = Field(default=None, max_length=160)
    meal_type: MealType | None = None
    notes: str | None = Field(default=None, max_length=500)
    day: date | None = None
    items: list[MealItemIn] | None = None


class Settings(BaseModel):
    calorie_target: float = Field(default=2200, ge=0, le=20000)
    protein_target: float = Field(default=160, ge=0, le=2000)
    carbs_target: float = Field(default=220, ge=0, le=2000)
    fat_target: float = Field(default=70, ge=0, le=2000)


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    calorie_target: float = Field(default=2200, ge=0, le=20000)
    protein_target: float = Field(default=160, ge=0, le=2000)
    carbs_target: float = Field(default=220, ge=0, le=2000)
    fat_target: float = Field(default=70, ge=0, le=2000)
    avatar_color: str = Field(default="#3b82f6", max_length=20)
    track_back_photo: int = Field(default=0, ge=0, le=1)


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    calorie_target: float | None = Field(default=None, ge=0, le=20000)
    protein_target: float | None = Field(default=None, ge=0, le=2000)
    carbs_target: float | None = Field(default=None, ge=0, le=2000)
    fat_target: float | None = Field(default=None, ge=0, le=2000)
    avatar_color: str | None = Field(default=None, max_length=20)
    track_back_photo: int | None = Field(default=None, ge=0, le=1)


class TargetPreviewIn(BaseModel):
    sex: str | None = "male"
    weight_kg: float = Field(gt=20, le=500)
    height_cm: float = Field(gt=50, le=260)
    age: int = Field(gt=10, le=120)
    activity_level: str | None = "moderate"
    goal: str | None = "maintain"
    goal_rate_kg_per_week: float = Field(default=0.5, ge=0.0, le=2.0)


class OnboardingIn(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    avatar_color: str | None = Field(default=None, max_length=20)
    sex: str | None = None
    birth_year: int | None = Field(default=None, ge=1900, le=2030)
    height_cm: float | None = Field(default=None, ge=50, le=260)
    current_weight_kg: float | None = Field(default=None, gt=0, le=500)
    activity_level: str | None = "moderate"
    goal: str | None = "maintain"
    goal_rate_kg_per_week: float = Field(default=0.5, ge=0.0, le=2.0)
    calorie_target: float | None = Field(default=None, ge=500, le=20000)
    protein_target: float | None = Field(default=None, ge=0, le=2000)
    carbs_target: float | None = Field(default=None, ge=0, le=2000)
    fat_target: float | None = Field(default=None, ge=0, le=2000)
    equipment_keys: list[str] | None = None
    preferred_duration_min: int | None = Field(default=25, ge=10, le=90)
    preferred_level: str | None = Field(default="intermediate")
    workout_days_per_week: int | None = Field(default=3, ge=1, le=7)


class WeightIn(BaseModel):
    weight_kg: float = Field(gt=0, le=500)
    day: date | None = None
    notes: str = Field(default="", max_length=300)


class EquipmentIn(BaseModel):
    item_key: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=200)


class WorkoutGenerateIn(BaseModel):
    category: str = Field(default="full_body")
    duration_min: int = Field(default=25, ge=10, le=90)
    level: str = Field(default="intermediate")
    custom_prompt: str | None = Field(default=None, max_length=500)


class WorkoutLogIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    category: str = Field(default="full_body")
    duration_min: int = Field(default=20, ge=1, le=300)
    intensity: str = Field(default="medium")
    equipment_used: list[str] = Field(default_factory=list)
    routine: list | dict = Field(default_factory=list)
    routine_json: list | dict | None = None
    day: date | None = None
    notes: str = Field(default="", max_length=500)


