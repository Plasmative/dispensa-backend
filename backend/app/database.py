"""
database.py — PostgreSQL connection + SQLAlchemy models
Uses asyncpg for async support with FastAPI
"""

import os
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float,
    Integer, String, Text, func
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# ── Connection ────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

import re

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# asyncpg doesn't accept sslmode/channel_binding in the URL — strip them and pass ssl via connect_args
DATABASE_URL = re.sub(r"[?&](sslmode|channel_binding)=[^&]*", "", DATABASE_URL).rstrip("?&")

engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"ssl": True})
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ── Base ──────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Tables ────────────────────────────────────────────────────────────────────

class PantryItem(Base):
    __tablename__ = "pantry_items"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String(100), nullable=False)
    category        = Column(String(50), default="other")
    quantity        = Column(Float, default=1.0)
    unit            = Column(String(30), default="unit")
    added_date      = Column(Date, default=date.today)
    expiration_date = Column(Date, nullable=True)
    is_fresh_produce= Column(Boolean, default=False)
    notes           = Column(String(200), nullable=True)
    created_at      = Column(DateTime, server_default=func.now())


class WasteLog(Base):
    __tablename__ = "waste_log"

    id          = Column(Integer, primary_key=True, index=True)
    item_name   = Column(String(100), nullable=False)
    outcome     = Column(String(20), nullable=False)  # "used" | "wasted"
    logged_date = Column(Date, default=date.today)
    notes       = Column(String(200), nullable=True)
    created_at  = Column(DateTime, server_default=func.now())


class RecipeFeedback(Base):
    __tablename__ = "recipe_feedback"

    id           = Column(Integer, primary_key=True, index=True)
    recipe_name  = Column(String(150), nullable=False)
    ingredients  = Column(Text, nullable=True)   # JSON string
    rating       = Column(Integer, nullable=True) # 1-5
    user_notes   = Column(Text, nullable=True)
    was_removed  = Column(Boolean, default=False)
    created_at   = Column(DateTime, server_default=func.now())


# ── Create all tables ─────────────────────────────────────────────────────────
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
