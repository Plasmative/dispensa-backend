"""
filters.py — Anti-hallucination filter for Dispensa Consciente.

Rule: a recipe passes only if EVERY ingredient it lists is either:
  (a) in the user's ingredient list (after synonym resolution), OR
  (b) a recognised pantry staple.

The AI generates freely. This layer silently drops anything that doesn't
match reality. It never adds or invents ingredients.
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

# ── Pantry staples assumed present in every kitchen ───────────────────────
PANTRY_STAPLES: frozenset[str] = frozenset({
    "salt", "water", "oil", "olive oil", "vegetable oil", "butter",
    "sugar", "flour", "black pepper", "pepper", "white pepper",
    "vinegar", "baking powder", "baking soda", "soy sauce", "garlic",
})

# ── Synonym map: AI name → user-typed name ────────────────────────────────
SYNONYMS: dict[str, str] = {
    "mozzarella": "cheese", "cheddar": "cheese", "parmesan": "cheese",
    "feta": "cheese", "cream cheese": "cheese", "shredded cheese": "cheese",
    "grated cheese": "cheese",
    "egg": "eggs", "whole egg": "eggs", "large egg": "eggs",
    "green onion": "onion", "spring onion": "onion", "scallion": "onion",
    "red onion": "onion", "yellow onion": "onion", "shallot": "onion",
    "cherry tomato": "tomato", "cherry tomatoes": "tomato",
    "diced tomato": "tomato", "canned tomato": "tomato", "tomatoes": "tomato",
    "potatoes": "potato", "sweet potato": "potato",
    "white bread": "bread", "sandwich bread": "bread", "sourdough": "bread",
    "spaghetti": "pasta", "penne": "pasta", "fettuccine": "pasta",
    "noodles": "pasta", "rigatoni": "pasta",
    "chicken breast": "chicken", "chicken thigh": "chicken",
    "black beans": "beans", "kidney beans": "beans", "canned beans": "beans",
    "cooking oil": "oil", "vegetable broth": "water", "chicken broth": "water",
    "lemon juice": "lemon", "lime juice": "lime",
}

# ── Emoji heuristics ──────────────────────────────────────────────────────
_EMOJI_MAP: list[tuple[set[str], str]] = [
    ({"egg", "eggs"},                          "🍳"),
    ({"pasta", "noodle", "spaghetti"},         "🍝"),
    ({"rice"},                                 "🍚"),
    ({"bread", "toast"},                       "🍞"),
    ({"tomato"},                               "🍅"),
    ({"avocado"},                              "🥑"),
    ({"banana"},                               "🍌"),
    ({"potato"},                               "🥔"),
    ({"chicken"},                              "🍗"),
    ({"tuna", "fish", "salmon"},               "🐟"),
    ({"cheese"},                               "🧀"),
    ({"bean", "beans", "lentil", "chickpea"},  "🫘"),
    ({"soup", "stew", "broth"},                "🍲"),
    ({"salad"},                                "🥗"),
    ({"pancake", "crepe"},                     "🥞"),
    ({"oat", "oats"},                          "🥣"),
    ({"tortilla", "wrap"},                     "🫓"),
    ({"milk"},                                 "🥛"),
]


def _norm(text: str) -> str:
    return text.strip().lower()


def _resolve(ingredient: str) -> str:
    n = _norm(ingredient)
    if n in SYNONYMS:
        return SYNONYMS[n]
    for key, val in SYNONYMS.items():
        if key in n:
            return val
    return n


def _stem(word: str) -> str:
    if word.endswith("oes"): return word[:-2]
    if word.endswith("ies"): return word[:-3] + "y"
    if word.endswith("es") and len(word) > 4: return word[:-2]
    if word.endswith("s")  and len(word) > 3: return word[:-1]
    return word


def _user_has(ingredient: str, available: frozenset[str]) -> bool:
    resolved = _resolve(ingredient)
    if resolved in PANTRY_STAPLES or resolved in available:
        return True
    stemmed = _stem(resolved)
    if stemmed in available:
        return True
    for item in available:
        if _stem(item) == stemmed:
            return True
    # Substring guard: only for strings >= 4 chars to avoid "oil"→"foil"
    if len(resolved) >= 4:
        for item in available:
            if resolved in item or item in resolved:
                return True
    return False


def _pick_emoji(ingredients: list[str]) -> str:
    lower = {_resolve(i) for i in ingredients}
    for kws, emoji in _EMOJI_MAP:
        if kws & lower:
            return emoji
    return "🍽️"


def _normalise_time(raw: str | None) -> str | None:
    if not raw:
        return None
    mapping = {
        "quick": "under 15 min", "medium": "15–30 min", "long": "30+ min",
        "5 min": "5 min", "10 min": "10 min", "15 min": "15 min",
        "20 min": "20 min", "25 min": "25 min", "30 min": "30 min",
        "45 min": "45 min",
    }
    return mapping.get(str(raw).strip().lower(), raw)


def filter_recipes(
    raw_recipes: list[dict],
    user_ingredients: list[str],
    expires_soon: list[str] | None = None,
    max_results: int = 3,
) -> list[dict]:
    """
    Returns enriched recipe dicts — only those the user can actually make.
    Sorted by: expiry-priority score → ingredient coverage.
    """
    available   = frozenset(_resolve(i) for i in user_ingredients)
    expiring    = frozenset(_resolve(e) for e in (expires_soon or []))
    valid: list[dict] = []
    rejected = 0

    for recipe in raw_recipes:
        name      = recipe.get("name", "<unnamed>")
        req_ings  = recipe.get("ingredients", [])
        if not req_ings:
            rejected += 1
            continue

        failing = [i for i in req_ings if not _user_has(i, available)]
        if failing:
            logger.info("REJECT '%s' — missing: %s", name, ", ".join(failing))
            rejected += 1
            continue

        used = [i for i in req_ings if _resolve(i) not in PANTRY_STAPLES]
        extras = [
            o for o in recipe.get("optional_ingredients", [])
            if _user_has(o, available) and _resolve(o) not in PANTRY_STAPLES
        ]
        uses_expiring = [
            i for i in used
            if any(e in _resolve(i) or _resolve(i) in e for e in expiring)
        ]

        valid.append({
            **recipe,
            "time_label":         _normalise_time(recipe.get("time") or recipe.get("time_label")),
            "emoji":              recipe.get("emoji") or _pick_emoji(req_ings),
            "ingredients_used":   used,
            "available_extras":   extras,
            "uses_expiring":      uses_expiring,
            "_score":             len(uses_expiring) * 10 + len(used),
        })

    if rejected:
        logger.info("Filter: %d accepted, %d rejected out of %d",
                    len(valid), rejected, len(raw_recipes))

    valid.sort(key=lambda r: r["_score"], reverse=True)
    return valid[:max_results]
