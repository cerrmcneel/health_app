"""Pydantic request/response models."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Confidence = Literal["low", "medium", "high"]
MealType = Literal["breakfast", "lunch", "dinner", "snack", "other"]
Pose = Literal["front", "profile"]


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
    source: Literal["photo", "manual"] = "manual"
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
