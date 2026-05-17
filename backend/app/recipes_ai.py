"""
recipes_ai.py — AI recipe generation for Dispensa Consciente.

FREE AI provider: OpenRouter  →  set OPENROUTER_API_KEY
                                  free models: mistralai/mistral-7b-instruct:free
                                               google/gemma-3-4b-it:free

Paid fallback:   Anthropic    →  set ANTHROPIC_API_KEY
                                  set RECIPE_AI_PROVIDER=anthropic

Switch provider:
    RECIPE_AI_PROVIDER=openrouter   (default — FREE)
    RECIPE_AI_PROVIDER=anthropic    (paid)

The AI is ALLOWED to hallucinate. filters.filter_recipes() catches everything
before the user ever sees an invalid ingredient.
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

# ── Constraint-first system prompt ───────────────────────────────────────────
#
# Design rationale:
#   1. Hard rule FIRST — LLMs weight earlier tokens more heavily
#   2. Explicit pantry-staple allowlist — "these are the ONLY free extras"
#   3. Negative example — shows the exact failure mode to avoid
#   4. JSON-only output — no prose wrapper
#   5. "If unsure, make simpler recipes" — safety valve for few-ingredient inputs

SYSTEM_PROMPT = """\
You are a home-cooking assistant helping users reduce food waste.

════════════════════════════════════════
HARD RULE — READ THIS FIRST:
You may ONLY use ingredients from the user's provided list.
The ONLY permitted free extras are: salt, oil, water, pepper, garlic.
DO NOT add any other ingredient, even if it would improve the dish.
If a recipe normally needs something not on the user's list — skip that recipe.
════════════════════════════════════════

Respond with ONLY a valid JSON array. No markdown fences. No explanation. No text before or after.

Each element must have exactly these keys:
  "name"         — string, a creative and appetizing recipe name
  "ingredients"  — array of strings, ONLY ingredients from user list + allowed extras
  "description"  — string, one vivid and enticing sentence that makes the dish sound delicious
                   (mention key flavors, textures, or the cooking technique)
  "time"         — string, one of: "quick" | "medium" | "long"
                   (quick = under 15 min, medium = 15-30 min, long = over 30 min)

Generate 4 to 5 recipes. Make them VARIED and interesting:
  • Use different cooking techniques across recipes: raw/salad, sautéed, scrambled,
    roasted, stir-fried, grilled, soup/broth, baked — do NOT repeat the same method.
  • Vary meal type: snack, breakfast, light lunch, hearty main, one-pot.
  • Include at least one quick option (under 15 min).
  • Make each recipe meaningfully different — different technique AND different focus ingredient.
  • If ingredients are limited, be creative with seasoning and cooking method rather than adding extras.

EXAMPLE of what NOT to do (user has: eggs, tomato):
  WRONG: {"ingredients": ["eggs", "tomato", "heavy cream"]}  ← heavy cream not available
  RIGHT: {"ingredients": ["eggs", "tomato"]}
"""

RETRY_PROMPT = """\
Your previous response was not valid JSON. Return ONLY the JSON array.
Start with [ and end with ]. No markdown. No explanation.
"""

STEPS_SYSTEM = """\
You are a friendly home cooking assistant. Given a recipe name, its ingredients, and the number of servings,
return ONLY a JSON object with exactly two keys:
- "steps": array of 5-8 clear step-by-step cooking instructions (write them in the language specified by the user)
- "ingredients": array of ingredient objects scaled for the given number of servings, each with:
    "name" (string), "quantity" (number — must be a positive number, never null or zero), "unit" (string)

CRITICAL RULES:
1. You MUST always include the "ingredients" array with real, practical quantities for the given servings.
2. Base quantities on standard home cooking: e.g. 2 eggs per person, 1 tomato per person, 1 tbsp oil per serving.
3. Scale the quantities proportionally: if 1 serving = 2 eggs, then 4 servings = 8 eggs.
4. Every ingredient in "steps" must appear in "ingredients" with a quantity and unit.

Return ONLY the JSON object. No markdown, no explanation.
Example for 2 servings of scrambled eggs with tomato (Spanish):
{"steps":["Bate los huevos en un tazón con sal y pimienta.","Pica el tomate en cubos pequeños.","Calienta el aceite en sartén a fuego medio.","Agrega los huevos batidos y revuelve constantemente.","Añade el tomate picado y cocina 1 minuto más.","Sirve caliente."],"ingredients":[{"name":"huevos","quantity":4,"unit":"piezas"},{"name":"tomate","quantity":2,"unit":"piezas"},{"name":"aceite","quantity":2,"unit":"cdas"},{"name":"sal","quantity":1,"unit":"pizca"},{"name":"pimienta","quantity":1,"unit":"pizca"}]}
"""

# ── Groq (FREE) ───────────────────────────────────────────────────────────────

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

LANG_NAMES = {
    "es": "Spanish",
    "en": "English",
    "pt": "Portuguese (Brazilian)",
}


def _call_groq(messages: list[dict]) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY is not set. Get a free key at console.groq.com")

    payload = {
        "model":      GROQ_MODEL,
        "messages":   messages,
        "max_tokens": 1400,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(GROQ_URL, json=payload, headers=headers)
        resp.raise_for_status()

    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Groq error: {data['error']}")

    return data["choices"][0]["message"]["content"]


def _generate_groq(user_prompt: str) -> list[dict]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_prompt},
    ]
    raw = _call_groq(messages)
    result = _parse_json(raw)
    if result:
        return result

    logger.info("Groq: first parse failed — retrying with repair prompt")
    messages += [
        {"role": "assistant", "content": raw},
        {"role": "user",      "content": "Return ONLY the JSON array. No explanation, no markdown."},
    ]
    return _parse_json(_call_groq(messages)) or []


# ── Anthropic (paid fallback) ─────────────────────────────────────────────────

def _generate_anthropic(user_prompt: str) -> list[dict]:
    try:
        import anthropic as _anthropic
    except ImportError:
        raise ImportError("pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set.")

    client = _anthropic.Anthropic(api_key=api_key)

    def _call(system: str, msgs: list[dict]) -> str:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1400,
            system=system,
            messages=msgs,
        )
        return resp.content[0].text

    raw = _call(SYSTEM_PROMPT, [{"role": "user", "content": user_prompt}])
    result = _parse_json(raw)
    if result:
        return result

    logger.info("Anthropic: first parse failed — retrying")
    retry_raw = _call(
        RETRY_PROMPT,
        [
            {"role": "user",      "content": user_prompt},
            {"role": "assistant", "content": raw},
            {"role": "user",      "content": "Return only the JSON array."},
        ],
    )
    return _parse_json(retry_raw) or []


# ── JSON parser ───────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> list[dict] | None:
    """
    Robustly extract a JSON array from an LLM response.
    Handles: markdown fences, leading/trailing prose, trailing commas.
    """
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()

    start = cleaned.find("[")
    end   = cleaned.rfind("]")
    if start == -1 or end == -1:
        logger.warning("No JSON array found in LLM output (len=%d)", len(raw))
        return None

    candidate = cleaned[start:end + 1]
    try:
        data = json.loads(candidate)
        if isinstance(data, list) and data:
            return data
    except json.JSONDecodeError:
        # Fix trailing commas — common LLM mistake
        fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            data = json.loads(fixed)
            if isinstance(data, list) and data:
                logger.info("Recovered JSON after trailing-comma fix")
                return data
        except json.JSONDecodeError as e:
            logger.warning("JSON parse failed after fix: %s", e)

    return None


def _parse_json_object(raw: str) -> dict | None:
    """Extract a JSON object from an LLM response."""
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    start = cleaned.find("{")
    end   = cleaned.rfind("}")
    if start == -1 or end == -1:
        return None
    candidate = cleaned[start:end + 1]
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            data = json.loads(fixed)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError as e:
            logger.warning("JSON object parse failed: %s", e)
    return None


# ── User prompt builder ───────────────────────────────────────────────────────

def _build_prompt(
    ingredients: list[str],
    time_preference: str | None,
    type_preference: str | None,
    expires_soon: list[str] | None,
    dietary_restrictions: list[str] | None = None,
    language: str = "es",
) -> str:
    lang_name = LANG_NAMES.get(language, "Spanish")
    lines = [
        f"Available ingredients: {', '.join(ingredients)}",
        "(You may also freely add: salt, oil, water, pepper, garlic)",
        "",
        f"IMPORTANT: Write ALL text fields (name, description) in {lang_name}.",
    ]
    if dietary_restrictions:
        lines.append(f"DIETARY RESTRICTIONS (strictly required): {', '.join(dietary_restrictions)}. Do NOT suggest any recipe that violates these.")

    if time_preference == "quick":
        lines.append("Preference: fast recipes only — under 15 minutes please.")
    elif time_preference == "have time":
        lines.append("Preference: I have time to cook — recipes up to 45 minutes are fine.")

    if type_preference == "light":
        lines.append("Preference: something light — a snack or small meal.")
    elif type_preference == "filling":
        lines.append("Preference: something hearty and filling.")

    if expires_soon:
        lines += [
            "",
            f"⚠️  PRIORITY: please include at least one recipe that uses "
            f"{', '.join(expires_soon)} — these ingredients expire soon.",
        ]

    lines += [
        "",
        "Generate 4–5 creative, varied recipes as a JSON array. Return ONLY the array, nothing else.",
    ]
    return "\n".join(lines)


# ── Public interface ─────────────────────────────────────────────────────────

def generate_recipes(
    ingredients: list[str],
    time_preference: str | None = None,
    type_preference: str | None = None,
    expires_soon: list[str] | None = None,
    dietary_restrictions: list[str] | None = None,
    language: str = "es",
) -> list[dict]:
    """
    Generate recipe candidates using AI.

    Returns raw (UNVALIDATED) dicts.
    Always call filters.filter_recipes() on the result.

    Provider selection (env var RECIPE_AI_PROVIDER):
      "groq"        — FREE, uses Groq + llama-3.3-70b (default)
      "anthropic"   — paid, uses Claude Haiku
    """
    prompt   = _build_prompt(ingredients, time_preference, type_preference, expires_soon, dietary_restrictions, language)
    provider = os.environ.get("RECIPE_AI_PROVIDER", "openrouter").lower()

    logger.info("Generating recipes via %s | ingredients=%s", provider, ingredients)

    try:
        if provider == "anthropic":
            return _generate_anthropic(prompt)
        else:
            return _generate_groq(prompt)
    except Exception as exc:
        logger.error("Recipe generation failed [%s]: %s", provider, exc)
        raise RuntimeError(f"Recipe generation failed: {exc}") from exc


def generate_steps(recipe_name: str, ingredients: list[str], servings: int = 1, language: str = "es") -> dict:
    lang_name = LANG_NAMES.get(language, "Spanish")
    user_msg = (
        f"Recipe: {recipe_name}\n"
        f"Ingredients: {', '.join(ingredients)}\n"
        f"Servings: {servings}\n\n"
        f"Return a JSON object with 'steps' (array of cooking instructions in {lang_name}) and "
        f"'ingredients' (array of {{name, quantity, unit}} scaled for {servings} serving(s))."
    )
    messages = [
        {"role": "system", "content": STEPS_SYSTEM},
        {"role": "user",   "content": user_msg},
    ]
    try:
        raw = _call_groq(messages)
        obj = _parse_json_object(raw)
        if obj and "steps" in obj:
            steps = [str(s) for s in obj.get("steps", [])]
            ings  = obj.get("ingredients", [])
            return {"steps": steps, "ingredients": ings}
        # Fallback: try old array format
        arr = _parse_json(raw)
        if isinstance(arr, list) and arr:
            return {"steps": [str(s) for s in arr], "ingredients": []}
    except Exception as exc:
        logger.error("Steps generation failed: %s", exc)
    return {"steps": ["No se pudieron cargar los pasos. Intenta de nuevo."], "ingredients": []}
