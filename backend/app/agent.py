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

LANG_MSGS = {
    "es": {
        "start_prefix":      "¡Perfecto, podemos cocinar algo con {preview}{more}! 😊\n\n",
        "ask_expiry":        "Veo que algunos ingredientes pueden vencer pronto 🍅\n¿Quieres que **priorice recetas que los usen primero**, o prefieres las mejores opciones?",
        "ask_time_few":      "Con pocos ingredientes aún podemos hacer algo rico 😊\n¿Prefieres algo **muy simple** o algo un poco más **creativo**?",
        "ask_time_many":     "¡Tienes bastantes ingredientes! 🎉\n¿Quieres algo **rápido** o tienes tiempo para algo más **elaborado**?",
        "ask_time":          "¿Quieres algo **rápido** (menos de 15 min) o tienes **más tiempo** para cocinar?",
        "after_expiry_yes":  "¡Perfecto! 🌿\nUna cosa más — ¿buscas algo **ligero** o algo más **contundente**?",
        "after_expiry_no":   "Sin problema.\n¿Quieres algo **ligero** o algo más **contundente**?",
        "after_time":        "¡Entendido! Una cosa más — ¿buscas algo **ligero** o algo más **contundente**?",
        "no_recipes":        "Parece que no tenemos suficientes ingredientes para una receta completa 😅\nPero no tires nada — mira el consejo abajo 👇",
        "opener_expiry":     "Aquí hay opciones que usan tu **{expiring}** antes de que venza:\n",
        "opener_quick":      "Opciones rápidas — esto podemos hacer ahora mismo:\n",
        "opener_time":       "Ya que tienes tiempo, aquí hay unas buenas opciones:\n",
        "opener_default":    "Aquí hay algunas buenas opciones con lo que tienes:\n",
        "footer":            "¡Todo con lo que ya tienes en casa! 👍",
        "waste_note":        "Esto ayuda a usar tu {expiring} antes de que venza 🍅",
        "fallback_add":      "Intenta agregar huevos, pasta o pan para desbloquear más recetas.",
        "fallback_combine":  "Podrías combinar {items} simplemente. ¡A veces las mejores comidas son improvisadas! 🙂",
        "done_msg":          "Ya encontramos tus recetas 🙂 ¿Quieres empezar de nuevo?",
        "error_msg":         "No pude encontrar tu sesión. Por favor empieza de nuevo.",
        "gen_error":         "Tuve un problema generando recetas 😔 Por favor intenta en un momento.",
        "more":              " y {n} más",
    },
    "en": {
        "start_prefix":      "Great, we can cook something with {preview}{more}! 😊\n\n",
        "ask_expiry":        "I see some ingredients are expiring soon 🍅\nShould I **prioritize recipes that use them first**, or show the best options overall?",
        "ask_time_few":      "With just a few ingredients we can still make something tasty 😊\nDo you prefer something **very simple** or a bit more **creative**?",
        "ask_time_many":     "You've got plenty of ingredients! 🎉\nDo you want something **quick** or do you have time for something more **elaborate**?",
        "ask_time":          "Do you want something **quick** (under 15 min) or do you have **more time** to cook?",
        "after_expiry_yes":  "Perfect! 🌿\nOne more thing — are you looking for something **light** or something more **hearty**?",
        "after_expiry_no":   "No problem.\nAre you looking for something **light** or something more **hearty**?",
        "after_time":        "Got it! One more thing — are you looking for something **light** or something more **hearty**?",
        "no_recipes":        "Seems like we don't have enough ingredients for a full recipe 😅\nBut don't throw anything out — check the tip below 👇",
        "opener_expiry":     "Here are options that use your **{expiring}** before it expires:\n",
        "opener_quick":      "Quick options — we can make these right now:\n",
        "opener_time":       "Since you have time, here are some great options:\n",
        "opener_default":    "Here are some great options with what you have:\n",
        "footer":            "All with what you already have at home! 👍",
        "waste_note":        "This helps use your {expiring} before it expires 🍅",
        "fallback_add":      "Try adding eggs, pasta or bread to unlock more recipes.",
        "fallback_combine":  "You could simply combine {items}. Sometimes the best meals are improvised! 🙂",
        "done_msg":          "We already found your recipes 🙂 Want to start over?",
        "error_msg":         "I couldn't find your session. Please start again.",
        "gen_error":         "I had a problem generating recipes 😔 Please try again in a moment.",
        "more":              " and {n} more",
    },
    "pt": {
        "start_prefix":      "Ótimo, podemos cozinhar algo com {preview}{more}! 😊\n\n",
        "ask_expiry":        "Vejo que alguns ingredientes estão prestes a vencer 🍅\nDevo **priorizar receitas que os usem primeiro**, ou mostrar as melhores opções?",
        "ask_time_few":      "Com poucos ingredientes ainda podemos fazer algo gostoso 😊\nPrefere algo **bem simples** ou um pouco mais **criativo**?",
        "ask_time_many":     "Você tem bastantes ingredientes! 🎉\nQuer algo **rápido** ou tem tempo para algo mais **elaborado**?",
        "ask_time":          "Quer algo **rápido** (menos de 15 min) ou tem **mais tempo** para cozinhar?",
        "after_expiry_yes":  "Perfeito! 🌿\nMais uma coisa — quer algo **leve** ou algo mais **substancial**?",
        "after_expiry_no":   "Sem problema.\nQuer algo **leve** ou algo mais **substancial**?",
        "after_time":        "Entendido! Mais uma coisa — quer algo **leve** ou algo mais **substancial**?",
        "no_recipes":        "Parece que não temos ingredientes suficientes para uma receita completa 😅\nMas não jogue nada fora — veja a dica abaixo 👇",
        "opener_expiry":     "Aqui estão opções que usam seu **{expiring}** antes de vencer:\n",
        "opener_quick":      "Opções rápidas — podemos fazer agora mesmo:\n",
        "opener_time":       "Já que você tem tempo, aqui estão boas opções:\n",
        "opener_default":    "Aqui estão algumas boas opções com o que você tem:\n",
        "footer":            "Tudo com o que você já tem em casa! 👍",
        "waste_note":        "Isso ajuda a usar seu {expiring} antes de vencer 🍅",
        "fallback_add":      "Tente adicionar ovos, macarrão ou pão para desbloquear mais receitas.",
        "fallback_combine":  "Você poderia combinar {items} simplesmente. Às vezes as melhores refeições são improvisadas! 🙂",
        "done_msg":          "Já encontramos suas receitas 🙂 Quer começar de novo?",
        "error_msg":         "Não encontrei sua sessão. Por favor comece de novo.",
        "gen_error":         "Tive um problema ao gerar receitas 😔 Por favor tente novamente em um momento.",
        "more":              " e mais {n}",
    },
}


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


def _m(lang, key, **kwargs):
    msgs = LANG_MSGS.get(lang, LANG_MSGS["es"])
    tmpl = msgs.get(key, LANG_MSGS["es"].get(key, ""))
    return tmpl.format(**kwargs) if kwargs else tmpl


def _fallback_tip(ingredients, lang="es"):
    non = [i for i in ingredients if _resolve(i) not in PANTRY_STAPLES][:4]
    if not non:
        return _m(lang, "fallback_add")
    return _m(lang, "fallback_combine", items=" + ".join(non))


def _build_message(recipes, expires_soon, time_pref, type_pref, expiry_pref, lang="es"):
    if not recipes:
        return _m(lang, "no_recipes")
    if expiry_pref == "yes" and expires_soon:
        opener = _m(lang, "opener_expiry", expiring=", ".join(expires_soon))
    elif time_pref == "quick":
        opener = _m(lang, "opener_quick")
    elif time_pref == "have time":
        opener = _m(lang, "opener_time")
    else:
        opener = _m(lang, "opener_default")
    lines = [opener]
    for r in recipes:
        waste = f" ♻️ *{_m(lang, 'waste_note', expiring=', '.join(r.uses_expiring))}*" if r.uses_expiring else ""
        lines.append(f"{r.emoji} **{r.name}**{waste}")
        lines.append(f"   {r.description}")
        parts = []
        if r.time_label: parts.append(f"⏱ {r.time_label}")
        if r.available_extras: parts.append(f"✨ {', '.join(r.available_extras[:3])}")
        if parts: lines.append(f"   {' · '.join(parts)}")
        lines.append("")
    lines.append(_m(lang, "footer"))
    return "\n".join(lines)


def _run_generation(session):
    lang = session.get("language", "es")
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
            dietary_restrictions=session.get("dietary_restrictions", []),
            language=lang,
        )
    except RuntimeError as exc:
        logger.error("Generation error: %s", exc)
        return _m(lang, "gen_error"), [], "done", None

    filtered = filter_recipes(
        raw_recipes=raw,
        user_ingredients=session["ingredients"],
        expires_soon=session.get("expires_soon", []) if session.get("expiry_preference") == "yes" else [],
        max_results=3,
    )
    suggestions = []
    for r in filtered:
        waste_note = _m(lang, "waste_note", expiring=", ".join(r["uses_expiring"])) if r.get("uses_expiring") else None
        suggestions.append(RecipeSuggestion(
            name=r["name"], emoji=r.get("emoji", "🍽️"),
            description=r.get("description", ""),
            ingredients_used=r.get("ingredients_used", []),
            available_extras=r.get("available_extras", []),
            uses_expiring=r.get("uses_expiring", []),
            waste_note=waste_note, time_label=r.get("time_label"),
        ))
    fallback = _fallback_tip(session["ingredients"], lang) if not suggestions else None
    message = _build_message(suggestions, session.get("expires_soon", []),
                             session.get("time_preference"), session.get("type_preference"),
                             session.get("expiry_preference"), lang)
    if len(_cache) >= _CACHE_MAX:
        _cache.popitem(last=False)
    _cache[key] = (message, suggestions)
    return message, suggestions, "done", fallback


def start_session(ingredients, expires_soon=None, dietary_restrictions=None, language="es"):
    sid = _new_id()
    lang = language if language in LANG_MSGS else "es"
    clean = [i.strip().lower() for i in ingredients if i.strip()]
    expiry = [e.strip().lower() for e in (expires_soon or [])]
    non_staple = [i for i in clean if _resolve(i) not in PANTRY_STAPLES]
    has_expiring = bool(expiry)
    few = len(non_staple) < 3
    many = len(non_staple) >= 6

    if has_expiring:
        question = _m(lang, "ask_expiry")
        first_step = "ask_expiry"
    elif few:
        question = _m(lang, "ask_time_few")
        first_step = "ask_time"
    elif many:
        question = _m(lang, "ask_time_many")
        first_step = "ask_time"
    else:
        question = _m(lang, "ask_time")
        first_step = "ask_time"

    _sessions[sid] = {
        "ingredients": clean, "expires_soon": expiry,
        "dietary_restrictions": [d.strip().lower() for d in (dietary_restrictions or [])],
        "language": lang,
        "step": first_step,
        "time_preference": None, "type_preference": None, "expiry_preference": None,
    }
    preview = ", ".join(clean[:4])
    n_more = len(clean) - 4
    more = _m(lang, "more", n=n_more) if n_more > 0 else ""
    prefix = _m(lang, "start_prefix", preview=preview, more=more)
    return sid, f"{prefix}{question}", first_step


def handle_reply(session_id, user_message):
    s = _sessions.get(session_id)
    if not s:
        return ("No pude encontrar tu sesión. Por favor empieza de nuevo.", [], "error", None)

    lang = s.get("language", "es")

    if s["step"] == "ask_expiry":
        s["expiry_preference"] = _detect_expiry(user_message)
        s["step"] = "ask_type"
        key = "after_expiry_yes" if s["expiry_preference"] == "yes" else "after_expiry_no"
        return _m(lang, key), [], "ask_type", None

    if s["step"] == "ask_time":
        s["time_preference"] = _detect_time(user_message)
        s["step"] = "ask_type"
        return _m(lang, "after_time"), [], "ask_type", None

    if s["step"] == "ask_type":
        s["type_preference"] = _detect_type(user_message)
        s["step"] = "done"
        return _run_generation(s)

    return _m(lang, "done_msg"), [], "done", None


def get_cache_stats():
    return {"entries": len(_cache), "max": _CACHE_MAX}
