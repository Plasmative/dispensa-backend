"""
main.py — Dispensa Consciente v5 (Online)

Endpoints:
  Cooking agent:
    POST /start
    POST /reply

  Pantry:
    GET    /pantry
    POST   /pantry
    PATCH  /pantry/{id}
    DELETE /pantry/{id}
    POST   /pantry/{id}/log   → log as used or wasted

  Stats:
    GET /stats

  Recipe feedback:
    POST /feedback

  Debug:
    GET /health
    GET /cache-stats
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import get_cache_stats, handle_reply, start_session
from app.recipes_ai import generate_steps, parse_item, recognize_ingredient
from app.database import PantryItem, RecipeFeedback, WasteLog, get_db, init_db
from app.expiry import calculate_expiry, days_until_expiry, get_freshness_emoji, get_freshness_status, is_fresh_produce
from app.schemas import (
    PantryItemCreate, PantryItemOut, PantryItemUpdate,
    ParseItemRequest, ParseItemResponse,
    RecipeFeedbackCreate, RecipeFeedbackOut,
    RecipeStepsRequest, RecipeStepsResponse,
    ReplyRequest, ReplyResponse,
    ScanRequest, ScanResponse,
    StartRequest, StartResponse,
    WasteLogCreate, WasteLogOut, WasteStats,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database ready")
    yield

app = FastAPI(
    title="Dispensa Consciente",
    version="5.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helper ────────────────────────────────────────────────────────────────────

def enrich_item(item: PantryItem) -> PantryItemOut:
    status = get_freshness_status(item.expiration_date)
    return PantryItemOut(
        id=item.id,
        name=item.name,
        category=item.category,
        quantity=item.quantity,
        unit=item.unit,
        added_date=item.added_date,
        expiration_date=item.expiration_date,
        is_fresh_produce=item.is_fresh_produce,
        notes=item.notes,
        freshness_status=status,
        freshness_emoji=get_freshness_emoji(status),
        days_until_expiry=days_until_expiry(item.expiration_date),
    )


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "version": "5.0.0"}


# ── Cooking Agent ─────────────────────────────────────────────────────────────

@app.post("/start", response_model=StartResponse, tags=["agent"])
def start(req: StartRequest):
    cleaned = [i.strip() for i in req.ingredients if i.strip()]
    if not cleaned:
        raise HTTPException(422, "Please provide at least one ingredient.")
    sid, message, step, recipes, fallback = start_session(
        ingredients=cleaned,
        expires_soon=req.expires_soon,
        dietary_restrictions=req.dietary_restrictions,
        language=req.language,
        saved_time=req.saved_time,
        saved_type=req.saved_type,
    )
    logger.info("NEW SESSION %s | ings=%s | step=%s", sid, cleaned, step)
    return StartResponse(session_id=sid, message=message, step=step, recipes=recipes or [], fallback_tip=fallback)


@app.post("/reply", response_model=ReplyResponse, tags=["agent"])
def reply(req: ReplyRequest):
    if not req.session_id or not req.message.strip():
        raise HTTPException(422, "session_id and message are required.")
    message, recipes, step, fallback_tip = handle_reply(req.session_id, req.message.strip())
    return ReplyResponse(
        session_id=req.session_id,
        message=message, recipes=recipes,
        fallback_tip=fallback_tip, step=step,
    )


# ── Pantry ────────────────────────────────────────────────────────────────────

@app.get("/pantry", response_model=list[PantryItemOut], tags=["pantry"])
async def get_pantry(
    status: Optional[str] = None,   # fresh | use_soon | expired
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PantryItem).order_by(PantryItem.expiration_date))
    items = result.scalars().all()
    enriched = [enrich_item(i) for i in items]
    if status:
        enriched = [i for i in enriched if i.freshness_status == status]
    return enriched


@app.post("/pantry", response_model=PantryItemOut, tags=["pantry"])
async def add_pantry_item(
    req: PantryItemCreate,
    db: AsyncSession = Depends(get_db),
):
    fresh = is_fresh_produce(req.name)
    expiry = req.expiration_date

    # Auto-calculate expiry for fresh produce if not provided
    if fresh and expiry is None:
        expiry = calculate_expiry(req.name)

    item = PantryItem(
        name=req.name,
        category=req.category if req.category != "other" else ("produce" if fresh else "pantry"),
        quantity=req.quantity,
        unit=req.unit,
        added_date=date.today(),
        expiration_date=expiry,
        is_fresh_produce=fresh,
        notes=req.notes,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return enrich_item(item)


@app.patch("/pantry/{item_id}", response_model=PantryItemOut, tags=["pantry"])
async def update_pantry_item(
    item_id: int,
    req: PantryItemUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PantryItem).where(PantryItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found.")

    for field, value in req.model_dump(exclude_none=True).items():
        setattr(item, field, value)

    await db.commit()
    await db.refresh(item)
    return enrich_item(item)


@app.delete("/pantry/{item_id}", tags=["pantry"])
async def delete_pantry_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PantryItem).where(PantryItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found.")
    await db.delete(item)
    await db.commit()
    return {"deleted": item_id}


@app.post("/pantry/{item_id}/log", response_model=WasteLogOut, tags=["pantry"])
async def log_item_outcome(
    item_id: int,
    req: WasteLogCreate,
    db: AsyncSession = Depends(get_db),
):
    """Log an item as 'used' or 'wasted' and remove from pantry."""
    result = await db.execute(select(PantryItem).where(PantryItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found.")

    log = WasteLog(
        item_name=req.item_name or item.name,
        outcome=req.outcome,
        logged_date=date.today(),
        notes=req.notes,
    )
    db.add(log)
    await db.delete(item)
    await db.commit()
    await db.refresh(log)
    return log


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats", response_model=WasteStats, tags=["stats"])
async def get_stats(db: AsyncSession = Depends(get_db)):
    now = datetime.now()
    result = await db.execute(
        select(WasteLog).where(
            extract("month", WasteLog.logged_date) == now.month,
            extract("year",  WasteLog.logged_date) == now.year,
        )
    )
    logs = result.scalars().all()

    used   = [l for l in logs if l.outcome == "used"]
    wasted = [l for l in logs if l.outcome == "wasted"]
    total  = len(logs)

    return WasteStats(
        month=now.strftime("%B %Y"),
        total_logged=total,
        used_count=len(used),
        wasted_count=len(wasted),
        waste_percentage=round((len(wasted) / total * 100) if total else 0, 1),
        items_wasted=[l.item_name for l in wasted],
        zero_waste=len(wasted) == 0,
    )


# ── Ingredient Scanner ────────────────────────────────────────────────────────

@app.post("/scan-ingredient", response_model=ScanResponse, tags=["pantry"])
def scan_ingredient(req: ScanRequest):
    try:
        name = recognize_ingredient(req.image, req.language)
        return ScanResponse(name=name, success=bool(name))
    except Exception as exc:
        logger.warning("scan-ingredient failed: %s", exc)
        return ScanResponse(name="", success=False)


# ── Voice item parser ─────────────────────────────────────────────────────────

@app.post("/parse-item", response_model=ParseItemResponse, tags=["pantry"])
def parse_item_endpoint(req: ParseItemRequest):
    try:
        data = parse_item(req.text, req.language)
        return ParseItemResponse(
            name=data.get("name") or "",
            quantity=data.get("quantity"),
            unit=data.get("unit") or "",
            category=data.get("category") or "",
            expiration_date=data.get("expiration_date") or None,
        )
    except Exception as exc:
        logger.warning("parse-item failed: %s", exc)
        return ParseItemResponse()


# ── Recipe Steps ──────────────────────────────────────────────────────────────

@app.post("/recipe-steps", response_model=RecipeStepsResponse, tags=["agent"])
def recipe_steps(req: RecipeStepsRequest):
    result = generate_steps(req.recipe_name, req.ingredients, req.servings, req.language)
    return RecipeStepsResponse(
        recipe_name=req.recipe_name,
        steps=result.get("steps", []),
        ingredients=result.get("ingredients", []),
    )


# ── Recipe Feedback ───────────────────────────────────────────────────────────

@app.post("/feedback", response_model=RecipeFeedbackOut, tags=["feedback"])
async def save_feedback(
    req: RecipeFeedbackCreate,
    db: AsyncSession = Depends(get_db),
):
    fb = RecipeFeedback(
        recipe_name=req.recipe_name,
        ingredients=req.ingredients,
        rating=req.rating,
        user_notes=req.user_notes,
        was_removed=req.was_removed,
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    return fb


@app.get("/cache-stats", tags=["debug"])
def cache():
    return get_cache_stats()
