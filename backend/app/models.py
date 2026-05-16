"""
models.py — Dispensa Consciente v3

Changes from v2:
  - SessionState gains `context_flags` (drives adaptive question logic in agent.py)
  - SessionState gains `cache_key` (drives result caching in agent.py)
  - RecipeSuggestion gains `waste_note` (per-recipe expiry message)
  - ReplyResponse gains `fallback_tip` (shown when recipes=[] instead of burying it in message)
"""

from typing import Optional
from pydantic import BaseModel, Field


# ── /start ─────────────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    ingredients: list[str] = Field(
        ...,
        min_length=1,
        description="Ingredients the user currently has",
        examples=[["eggs", "cheese", "tomato"]],
    )
    expires_soon: list[str] = Field(
        default_factory=list,
        description="Ingredients that should be used urgently (optional)",
        examples=[["tomato"]],
    )


class StartResponse(BaseModel):
    session_id: str = Field(description="Opaque ID — pass back in /reply")
    message: str = Field(description="Agent's first question to the user")
    step: str = Field(description="Current conversation step")


# ── /reply ─────────────────────────────────────────────────────────────────

class ReplyRequest(BaseModel):
    session_id: str = Field(description="Session ID returned from /start")
    message: str = Field(
        description="User's free-text answer",
        examples=["quick"],
    )


class RecipeSuggestion(BaseModel):
    name: str
    emoji: str
    description: str
    ingredients_used: list[str]
    available_extras: list[str] = Field(
        description="Optional ingredients the user also has",
        default_factory=list,
    )
    uses_expiring: list[str] = Field(
        description="Expiring ingredients this recipe uses up",
        default_factory=list,
    )
    waste_note: Optional[str] = Field(
        default=None,
        description="Inline food-waste message when this recipe uses expiring items",
    )
    time_label: Optional[str] = None


class ReplyResponse(BaseModel):
    session_id: str
    message: str = Field(description="Agent's natural language response")
    recipes: list[RecipeSuggestion] = Field(default_factory=list)
    fallback_tip: Optional[str] = Field(
        default=None,
        description="Simple suggestion when no valid recipes exist",
    )
    step: str = Field(description="'done' when the conversation is complete")


# ── Internal session state (not exposed via API) ────────────────────────────

class ContextFlags(BaseModel):
    """
    Computed once at session start from the ingredient list.
    Drives which questions the agent asks and how it phrases them.
    """
    few_ingredients: bool = False     # < 3 non-staple ingredients
    many_ingredients: bool = False    # >= 6 non-staple ingredients
    has_expiring: bool = False        # expires_soon is non-empty
    expiry_asked: bool = False        # whether we already asked the expiry question


class SessionState(BaseModel):
    session_id: str
    ingredients: list[str]
    expires_soon: list[str] = Field(default_factory=list)
    time_preference: Optional[str] = None    # "quick" | "have time"
    type_preference: Optional[str] = None    # "light" | "filling" | "any"
    expiry_preference: Optional[str] = None  # "yes" | "no"
    step: str = "ask_time"                   # ask_time → ask_type → done
    #                                          (ask_expiry inserted when has_expiring)
    context: ContextFlags = Field(default_factory=ContextFlags)
    cache_key: Optional[str] = None          # set after preferences are known
