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
    # Basics
    "salt", "water", "oil", "olive oil", "vegetable oil", "butter",
    "sugar", "flour", "black pepper", "pepper", "white pepper",
    "baking powder", "baking soda", "garlic",
    # Acids & condiments
    "vinegar", "apple cider vinegar", "red wine vinegar", "white vinegar",
    "soy sauce", "tomato paste", "hot sauce", "worcestershire sauce",
    # Liquid bases
    "broth", "stock", "chicken broth", "vegetable broth", "beef broth",
    # Dry spices every kitchen has
    "cumin", "paprika", "oregano", "thyme", "coriander", "bay leaf",
    "turmeric", "cinnamon", "cayenne", "chili powder", "red pepper flakes",
    "nutmeg", "ginger powder", "garlic powder", "onion powder",
})

# ── Synonym map: AI name → canonical name (resolves to user ingredient or pantry staple) ─────
SYNONYMS: dict[str, str] = {
    # ── Staples — CRITICAL: Spanish names for pantry-staple items ──────────
    "ajo": "garlic", "dientes de ajo": "garlic", "ajo picado": "garlic",
    "agua": "water",
    "azúcar": "sugar", "azucar": "sugar",
    "harina": "flour", "harina de trigo": "flour",
    "aceite vegetal": "vegetable oil", "aceite de girasol": "vegetable oil",
    "polvo para hornear": "baking powder", "levadura en polvo": "baking powder",
    "bicarbonato": "baking soda", "bicarbonato de sodio": "baking soda",
    # ── Cheese ──────────────────────────────────────────────────────────────
    "mozzarella": "cheese", "cheddar": "cheese", "parmesan": "cheese",
    "feta": "cheese", "cream cheese": "cheese", "shredded cheese": "cheese",
    "grated cheese": "cheese", "queso": "cheese", "queso rallado": "cheese",
    "queso fresco": "cheese", "queso fundido": "cheese", "queso parmesano": "cheese",
    "queso cheddar": "cheese", "queso mozzarella": "cheese",
    # ── Eggs ─────────────────────────────────────────────────────────────────
    "egg": "eggs", "whole egg": "eggs", "large egg": "eggs",
    "huevo": "eggs", "huevos": "eggs",
    # ── Onion ────────────────────────────────────────────────────────────────
    "green onion": "onion", "spring onion": "onion", "scallion": "onion",
    "red onion": "onion", "yellow onion": "onion", "shallot": "onion",
    "cebolla": "onion", "cebollín": "onion", "cebolleta": "onion",
    "cebolla morada": "onion", "cebolla blanca": "onion",
    # ── Tomato ───────────────────────────────────────────────────────────────
    "cherry tomato": "tomato", "cherry tomatoes": "tomato",
    "diced tomato": "tomato", "canned tomato": "tomato", "tomatoes": "tomato",
    "tomate": "tomato", "jitomate": "tomato", "tomates": "tomato",
    "tomate rojo": "tomato",
    # ── Potato ───────────────────────────────────────────────────────────────
    "potatoes": "potato", "sweet potato": "potato",
    "papa": "potato", "papas": "potato", "patata": "potato", "patatas": "potato",
    "camote": "potato", "boniato": "potato",
    # ── Bread ────────────────────────────────────────────────────────────────
    "white bread": "bread", "sandwich bread": "bread", "sourdough": "bread",
    "pan": "bread", "pan blanco": "bread", "pan integral": "bread",
    "pan de caja": "bread", "pan bimbo": "bread",
    # ── Pasta ────────────────────────────────────────────────────────────────
    "spaghetti": "pasta", "penne": "pasta", "fettuccine": "pasta",
    "noodles": "pasta", "rigatoni": "pasta", "fideos": "pasta",
    "espagueti": "pasta", "espaguetis": "pasta", "macarrones": "pasta",
    "tallarines": "pasta",
    # ── Chicken ──────────────────────────────────────────────────────────────
    "chicken breast": "chicken", "chicken thigh": "chicken", "chicken legs": "chicken",
    "pollo": "chicken", "pechuga": "chicken", "pechuga de pollo": "chicken",
    "muslo de pollo": "chicken", "pierna de pollo": "chicken",
    # ── Beef / pork / other meats ─────────────────────────────────────────────
    "carne": "beef", "carne de res": "beef", "res": "beef",
    "carne molida": "ground beef", "carne picada": "ground beef", "ground beef": "beef",
    "cerdo": "pork", "carne de cerdo": "pork", "lomo de cerdo": "pork", "costillas": "pork",
    "tocino": "bacon", "bacon": "bacon",
    "pavo": "turkey",
    # ── Fish & seafood ───────────────────────────────────────────────────────
    "atún": "tuna", "atun": "tuna",
    "salmón": "salmon",
    "bacalao": "cod",
    "camarón": "shrimp", "camarones": "shrimp", "langostinos": "shrimp",
    "sardina": "sardine", "sardinas": "sardine",
    # ── Beans / legumes ──────────────────────────────────────────────────────
    "black beans": "beans", "kidney beans": "beans", "canned beans": "beans",
    "frijoles": "beans", "frijol": "beans", "judías": "beans", "habichuelas": "beans",
    "lentejas": "lentils", "lenteja": "lentils",
    "garbanzos": "chickpeas", "garbanzo": "chickpeas",
    # ── Rice ─────────────────────────────────────────────────────────────────
    "arroz": "rice", "arroz blanco": "rice", "arroz integral": "rice",
    # ── Grains ───────────────────────────────────────────────────────────────
    "avena": "oats", "copos de avena": "oats", "rolled oats": "oats",
    "quinoa": "quinoa", "quinua": "quinoa",
    # ── Milk / dairy ─────────────────────────────────────────────────────────
    "leche": "milk", "leche entera": "milk", "leche descremada": "milk",
    "nata": "cream", "crema": "cream", "crema para batir": "cream",
    "crema agria": "sour cream", "crema ácida": "sour cream",
    "mantequilla": "butter",
    "yogur": "yogurt", "yogurt": "yogurt",
    # ── Oils & fats ──────────────────────────────────────────────────────────
    "cooking oil": "oil", "aceite": "oil",
    "aceite de oliva": "olive oil", "aove": "olive oil",
    # ── Vegetables ───────────────────────────────────────────────────────────
    "zanahoria": "carrot", "zanahorias": "carrot", "carrots": "carrot",
    "espinaca": "spinach", "espinacas": "spinach",
    "lechuga": "lettuce",
    "pepino": "cucumber", "pepinos": "cucumber",
    "calabacín": "zucchini", "calabacita": "zucchini", "calabacitas": "zucchini",
    "coliflor": "cauliflower",
    "brócoli": "broccoli", "brocoli": "broccoli",
    "pimiento": "bell pepper", "pimientos": "bell pepper",
    "pimiento rojo": "bell pepper", "pimiento verde": "bell pepper",
    "chile": "chili", "chiles": "chili", "chile verde": "chili",
    "jalapeño": "jalapeño",
    "maíz": "corn", "elote": "corn", "mazorca": "corn",
    "aguacate": "avocado", "palta": "avocado",
    "apio": "celery",
    "betabel": "beet", "remolacha": "beet",
    "hongos": "mushrooms", "champiñones": "mushrooms", "setas": "mushrooms",
    "mushroom": "mushrooms",
    "berenjena": "eggplant",
    "ejote": "green beans", "ejotes": "green beans", "judías verdes": "green beans",
    "chícharo": "peas", "chícharos": "peas", "guisantes": "peas",
    "col": "cabbage", "repollo": "cabbage",
    "nabo": "turnip",
    "poro": "leek", "puerro": "leek",
    # ── Fruits ───────────────────────────────────────────────────────────────
    "limón": "lemon", "lima": "lime",
    "naranja": "orange", "naranjas": "orange",
    "manzana": "apple", "manzanas": "apple",
    "pera": "pear", "peras": "pear",
    "plátano": "banana", "banano": "banana",
    "mango": "mango",
    "piña": "pineapple",
    "fresa": "strawberry", "fresas": "strawberry",
    "uva": "grape", "uvas": "grape",
    "durazno": "peach", "melocotón": "peach",
    # ── Nuts & seeds ─────────────────────────────────────────────────────────
    "nuez": "walnut", "nueces": "walnut",
    "almendra": "almond", "almendras": "almond",
    "cacahuate": "peanut", "maní": "peanut", "cacahuetes": "peanut",
    "semillas de girasol": "sunflower seeds",
    "chía": "chia", "linaza": "flaxseed",
    # ── Broth / stock ─────────────────────────────────────────────────────────
    "vegetable broth": "broth", "chicken broth": "broth", "beef broth": "broth",
    "caldo": "broth", "caldo de pollo": "broth", "caldo de verduras": "broth",
    "caldo de res": "broth",
    # ── Spices → pantry-staple English names ──────────────────────────────────
    "comino": "cumin", "pimentón": "paprika", "orégano": "oregano",
    "tomillo": "thyme", "cilantro molido": "coriander", "hoja de laurel": "bay leaf",
    "cúrcuma": "turmeric", "canela": "cinnamon", "pimienta cayena": "cayenne",
    "chile en polvo": "chili powder", "hojuelas de chile": "red pepper flakes",
    "nuez moscada": "nutmeg", "jengibre en polvo": "ginger powder",
    "ajo en polvo": "garlic powder", "cebolla en polvo": "onion powder",
    "pimienta negra": "black pepper", "pimienta": "pepper",
    "sal": "salt",
    # ── Acids & condiments ────────────────────────────────────────────────────
    "vinagre": "vinegar", "vinagre blanco": "vinegar",
    "salsa de soja": "soy sauce", "salsa soya": "soy sauce",
    "pasta de tomate": "tomato paste", "concentrado de tomate": "tomato paste",
    # ── Citrus juice ──────────────────────────────────────────────────────────
    "lemon juice": "lemon", "lime juice": "lime",
    "jugo de limón": "lemon", "zumo de limón": "lemon",
    "jugo de naranja": "orange",
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
