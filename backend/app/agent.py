"""
agent.py — Conversation logic (updated to use schemas.py models)
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections import OrderedDict
from typing import Optional

from app.filters import PANTRY_STAPLES, _resolve, filter_recipes
from app.schemas import RecipeSuggestion
from app.recipes_ai import generate_recipes
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_sessions: dict[str, dict] = {}
_cache: OrderedDict[str, tuple] = OrderedDict()
_CACHE_MAX = 100


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


_NEGATIONS  = {"not", "no", "never", "without", "avoid", "skip"}
_QUICK_KW   = {"quick", "fast", "rapido", "rápido", "pronto", "simple", "easy"}
_SLOW_KW    = {"time", "elaborate", "slow", "long", "complex", "creative", "tiempo"}
_LIGHT_KW   = {"light", "leve", "healthy", "snack", "small", "lite", "ligero", "ligera"}
_FILLING_KW = {"filling", "heavy", "hearty", "full", "satisfying", "hungry", "contundente"}
_YES_KW     = {"yes", "sure", "yep", "yeah", "ok", "okay", "si", "sí",
               "first", "those", "expiring", "primero", "vencen"}
_NO_KW      = {"no", "nope", "skip", "overall", "best", "any", "mejor"}


def _tokenise(text: str) -> list[str]:
    t = text.lower()
    t = re.sub(r"don't|dont|no quiero", "no ", t)
    t = re.sub(r"n't\b", " not ", t)
    return [tok for tok in re.split(r"[^a-záéíóúüñ0-9]+", t) if tok]


def _negated(tokens, idx):
    return bool(set(tokens[max(0, idx-3):idx]) & _NEGATIONS)


def _scan(text, kw):
    tokens = _tokenise(text)
    pos = neg = False
    for i, tok in enumerate(tokens):
        if tok in kw:
            if _negated(tokens, i): neg = True
            else: pos = True
    return pos, neg


def _detect_time(text):
    qp, qn = _scan(text, _QUICK_KW)
    sp, _  = _scan(text, _SLOW_KW)
    if qp and not qn: return "quick"
    if sp or qn:      return "have time"
    return "quick"


def _detect_type(text):
    lp, ln = _scan(text, _LIGHT_KW)
    fp, fn = _scan(text, _FILLING_KW)
    if lp and not ln and not fp: return "light"
    if fp and not fn:            return "filling"
    if ln:                       return "filling"
    if fn:                       return "light"
    return "any"


def _detect_expiry(text):
    yp, yn = _scan(text, _YES_KW)
    np_, _  = _scan(text, _NO_KW)
    return "yes" if (yp and not yn and not np_) else "no"


def _cache_key(s: dict) -> str:
    raw = "|".join([
        ",".join(sorted(s.get("ingredients", []))),
        s.get("time_preference") or "",
        s.get("type_preference") or "",
        s.get("expiry_preference") or "",
        ",".join(sorted(s.get("expires_soon", []))),
    ])
    return hashlib.md5(raw.encode()).hexdigest()


def _fallback_tip(ingredients):
    non = [i for i in ingredients if _resolve(i) not in PANTRY_STAPLES][:4]
    if not non:
        return "Intenta agregar huevos, pasta o pan para desbloquear más recetas."
    return f"Podrías combinar {' + '.join(non)} simplemente. ¡A veces las mejores comidas son improvisadas! 🙂"


def _build_message(recipes, expires_soon, time_pref, type_pref, expiry_pref):
    if not recipes:
        return "Parece que no tenemos suficientes ingredientes para una receta completa 😅\nPero no tires nada — mira el consejo abajo 👇"
    if expiry_pref == "yes" and expires_soon:
        opener = f"Aquí hay opciones que usan tu **{', '.join(expires_soon)}** antes de que venza:\n"
    elif time_pref == "quick":
        opener = "Opciones rápidas — esto podemos hacer ahora mismo:\n"
    elif time_pref == "have time":
        opener = "Ya que tienes tiempo, aquí hay unas buenas opciones:\n"
    else:
        opener = "Aquí hay algunas buenas opciones con lo que tienes:\n"
    lines = [opener]
    for r in recipes:
        waste = f" ♻️ *usa tu {', '.join(r.uses_expiring)}*" if r.uses_expiring else ""
        lines.append(f"{r.emoji} **{r.name}**{waste}")
        lines.append(f"   {r.description}")
        parts = []
        if r.time_label: parts.append(f"⏱ {r.time_label}")
        if r.available_extras: parts.append(f"✨ también puedes agregar: {', '.join(r.available_extras[:3])}")
        if parts: lines.append(f"   {' · '.join(parts)}")
        lines.append("")
    lines.append("¡Todo con lo que ya tienes en casa! 👍")
    return "\n".join(lines)


def _run_generation(session):
    key = _cache_key(session)
    if key in _cache:
        _cache.move_to_end(key)
        cached = _cache[key]
        return cached[0], cached[1], None
    try:
        raw = generate_recipes(
            ingredients=session["ingredients"],
            time_preference=session.get("time_preference"),
            type_preference=session.get("type_preference"),
            expires_soon=session.get("expires_soon", []) if session.get("expiry_preference") == "yes" else [],
        )
    except RuntimeError as exc:
        logger.error("Generation error: %s", exc)
        return "Tuve un problema generando recetas 😔 Por favor intenta en un momento.", [], None

    filtered = filter_recipes(
        raw_recipes=raw,
        user_ingredients=session["ingredients"],
        expires_soon=session.get("expires_soon", []) if session.get("expiry_preference") == "yes" else [],
        max_results=3,
    )
    suggestions = []
    for r in filtered:
        waste_note = None
        if r.get("uses_expiring"):
            waste_note = f"Esto ayuda a usar tu {', '.join(r['uses_expiring'])} antes de que venza 🍅"
        suggestions.append(RecipeSuggestion(
            name=r["name"], emoji=r.get("emoji", "🍽️"),
            description=r.get("description", ""),
            ingredients_used=r.get("ingredients_used", []),
            available_extras=r.get("available_extras", []),
            uses_expiring=r.get("uses_expiring", []),
            waste_note=waste_note, time_label=r.get("time_label"),
        ))
    fallback = _fallback_tip(session["ingredients"]) if not suggestions else None
    message = _build_message(suggestions, session.get("expires_soon", []),
                             session.get("time_preference"), session.get("type_preference"),
                             session.get("expiry_preference"))
    if len(_cache) >= _CACHE_MAX:
        _cache.popitem(last=False)
    _cache[key] = (message, suggestions)
    return message, suggestions, fallback


def start_session(ingredients, expires_soon=None):
    sid = _new_id()
    clean = [i.strip().lower() for i in ingredients if i.strip()]
    expiry = [e.strip().lower() for e in (expires_soon or [])]
    non_staple = [i for i in clean if _resolve(i) not in PANTRY_STAPLES]
    has_expiring = bool(expiry)
    few = len(non_staple) < 3
    many = len(non_staple) >= 6

    if has_expiring:
        question = ("Veo que algunos ingredientes pueden vencer pronto 🍅\n"
                    "¿Quieres que **priorice recetas que los usen primero**, o prefieres las mejores opciones?")
        first_step = "ask_expiry"
    elif few:
        question = ("Con pocos ingredientes aún podemos hacer algo rico 😊\n"
                    "¿Prefieres algo **muy simple** o algo un poco más **creativo**?")
        first_step = "ask_time"
    elif many:
        question = ("¡Tienes bastantes ingredientes! 🎉\n"
                    "¿Quieres algo **rápido** o tienes tiempo para algo más **elaborado**?")
        first_step = "ask_time"
    else:
        question = "¿Quieres algo **rápido** (menos de 15 min) o tienes **más tiempo** para cocinar?"
        first_step = "ask_time"

    _sessions[sid] = {
        "ingredients": clean, "expires_soon": expiry,
        "step": first_step,
        "time_preference": None, "type_preference": None, "expiry_preference": None,
    }
    preview = ", ".join(clean[:4])
    more = f" y {len(clean)-4} más" if len(clean) > 4 else ""
    return sid, f"¡Perfecto, podemos cocinar algo con {preview}{more}! 😊\n\n{question}", first_step


def handle_reply(session_id, user_message):
    s = _sessions.get(session_id)
    if not s:
        return ("No pude encontrar tu sesión. Por favor empieza de nuevo.", [], "error", None)

    if s["step"] == "ask_expiry":
        s["expiry_preference"] = _detect_expiry(user_message)
        s["step"] = "ask_time"
        msg = ("¡Perfecto! 🌿\nUna cosa más — ¿buscas algo **ligero** o algo más **contundente**?"
               if s["expiry_preference"] == "yes" else
               "Sin problema.\n¿Quieres algo **ligero** o algo más **contundente**?")
        return msg, [], "ask_type", None

    if s["step"] == "ask_time":
        s["time_preference"] = _detect_time(user_message)
        s["step"] = "ask_type"
        return ("¡Entendido! Una cosa más — ¿buscas algo **ligero** o algo más **contundente**?",
                [], "ask_type", None)

    if s["step"] == "ask_type":
        s["type_preference"] = _detect_type(user_message)
        s["step"] = "done"
        return _run_generation(s)

    return ("Ya encontramos tus recetas 🙂 ¿Quieres empezar de nuevo?", [], "done", None)


def get_cache_stats():
    return {"entries": len(_cache), "max": _CACHE_MAX}
