"""
schemas.py — Pydantic request/response models for all endpoints.
"""

from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


# ── Pantry ────────────────────────────────────────────────────────────────────

class PantryItemCreate(BaseModel):
    name: str
    category: str = "other"
    quantity: float = 1.0
    unit: str = "unit"
    expiration_date: Optional[date] = None  # manual date for packaged goods
    notes: Optional[str] = None


class PantryItemUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    expiration_date: Optional[date] = None
    notes: Optional[str] = None


class PantryItemOut(BaseModel):
    id: int
    name: str
    category: str
    quantity: float
    unit: str
    added_date: date
    expiration_date: Optional[date]
    is_fresh_produce: bool
    notes: Optional[str]
    # Computed fields
    freshness_status: str   # fresh | use_soon | expired | unknown
    freshness_emoji: str    # 🟢 🟡 🔴 ⚪
    days_until_expiry: Optional[int]

    class Config:
        from_attributes = True


# ── Waste Log ─────────────────────────────────────────────────────────────────

class WasteLogCreate(BaseModel):
    item_name: str
    outcome: str  # "used" | "wasted"
    notes: Optional[str] = None


class WasteLogOut(BaseModel):
    id: int
    item_name: str
    outcome: str
    logged_date: date
    notes: Optional[str]

    class Config:
        from_attributes = True


class WasteStats(BaseModel):
    month: str                    # e.g. "April 2026"
    total_logged: int
    used_count: int
    wasted_count: int
    waste_percentage: float
    items_wasted: list[str]       # names of wasted items
    zero_waste: bool


# ── Recipe Feedback ───────────────────────────────────────────────────────────

class RecipeFeedbackCreate(BaseModel):
    recipe_name: str
    ingredients: Optional[str] = None   # JSON string
    rating: Optional[int] = Field(None, ge=1, le=5)
    user_notes: Optional[str] = None
    was_removed: bool = False


class RecipeFeedbackOut(BaseModel):
    id: int
    recipe_name: str
    rating: Optional[int]
    user_notes: Optional[str]
    was_removed: bool

    class Config:
        from_attributes = True


# ── Cooking Agent (same as before) ───────────────────────────────────────────

class StartRequest(BaseModel):
    ingredients: list[str] = Field(..., min_length=1)
    expires_soon: list[str] = Field(default_factory=list)
    dietary_restrictions: list[str] = Field(default_factory=list)


class StartResponse(BaseModel):
    session_id: str
    message: str
    step: str


class ReplyRequest(BaseModel):
    session_id: str
    message: str


class RecipeSuggestion(BaseModel):
    name: str
    emoji: str = "🍽️"
    description: str
    ingredients_used: list[str] = Field(default_factory=list)
    available_extras: list[str] = Field(default_factory=list)
    uses_expiring: list[str]    = Field(default_factory=list)
    waste_note: Optional[str]   = None
    time_label: Optional[str]   = None


class ReplyResponse(BaseModel):
    session_id: str
    message: str
    recipes: list[RecipeSuggestion]  = Field(default_factory=list)
    fallback_tip: Optional[str]      = None
    step: str
