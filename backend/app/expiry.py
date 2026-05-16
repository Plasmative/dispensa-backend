"""
expiry.py — Expiration date calculation and freshness status.

For fresh produce: auto-calculates expiration from today.
For packaged goods: user provides the date manually.
"""

from datetime import date, timedelta
from typing import Optional

# ── Fresh produce shelf life (days from purchase) ─────────────────────────────
FRESH_PRODUCE_DAYS: dict[str, int] = {
    # Vegetables
    "tomato": 7, "tomatoes": 7,
    "lettuce": 5, "spinach": 5, "arugula": 4,
    "carrot": 21, "carrots": 21,
    "potato": 30, "potatoes": 30, "sweet potato": 21,
    "onion": 30, "onions": 30, "green onion": 7, "scallion": 7,
    "garlic": 30,
    "pepper": 10, "bell pepper": 10, "chili": 14,
    "cucumber": 7, "zucchini": 7, "courgette": 7,
    "broccoli": 7, "cauliflower": 7, "cabbage": 14,
    "mushroom": 7, "mushrooms": 7,
    "corn": 3, "peas": 5,
    "eggplant": 7, "aubergine": 7,
    "celery": 14, "leek": 10,
    "beet": 21, "radish": 7,
    "avocado": 4, "avocados": 4,
    "ginger": 21,
    "daikon": 14, "tofu": 5,
    # Fruits
    "banana": 5, "bananas": 5,
    "apple": 21, "apples": 21,
    "lemon": 21, "lemons": 21, "lime": 14, "limes": 14,
    "orange": 14, "oranges": 14,
    "strawberry": 5, "strawberries": 5,
    "blueberry": 7, "blueberries": 7,
    "grape": 10, "grapes": 10,
    "mango": 5, "mangoes": 5,
    "pineapple": 5,
    "watermelon": 7,
    "peach": 5, "pear": 7,
    # Dairy & protein
    "eggs": 28, "egg": 28,
    "milk": 7,
    "cheese": 14,
    "butter": 30,
    "yogurt": 14,
    "chicken": 3, "chicken breast": 3, "chicken thigh": 3,
    "beef": 4, "pork": 4, "fish": 2, "salmon": 2, "tuna": 2,
    "shrimp": 2, "prawns": 2,
    # Fresh herbs
    "basil": 5, "cilantro": 7, "parsley": 10,
    "mint": 7, "thyme": 10, "rosemary": 14,
}

# Items that are considered fresh produce (auto-expiry)
FRESH_PRODUCE_KEYWORDS = {
    "tomato", "lettuce", "spinach", "carrot", "potato", "onion",
    "pepper", "cucumber", "broccoli", "mushroom", "corn", "eggplant",
    "celery", "avocado", "banana", "apple", "lemon", "orange",
    "strawberry", "grape", "mango", "eggs", "milk", "chicken",
    "beef", "fish", "salmon", "tuna", "basil", "cilantro", "parsley",
    "garlic", "ginger", "tofu", "daikon", "leek", "zucchini",
}


def is_fresh_produce(name: str) -> bool:
    """Check if an ingredient is fresh produce (auto-expiry)."""
    lower = name.strip().lower()
    # Check exact match first
    if lower in FRESH_PRODUCE_DAYS:
        return True
    # Check if any keyword is in the name
    for kw in FRESH_PRODUCE_KEYWORDS:
        if kw in lower:
            return True
    return False


def calculate_expiry(name: str, added_date: date | None = None) -> Optional[date]:
    """
    Auto-calculate expiration date for fresh produce.
    Returns None for packaged goods (user must provide manually).
    """
    if added_date is None:
        added_date = date.today()

    lower = name.strip().lower()

    # Exact match
    if lower in FRESH_PRODUCE_DAYS:
        return added_date + timedelta(days=FRESH_PRODUCE_DAYS[lower])

    # Partial match
    for key, days in FRESH_PRODUCE_DAYS.items():
        if key in lower or lower in key:
            return added_date + timedelta(days=days)

    return None


def get_freshness_status(expiration_date: Optional[date]) -> str:
    """
    Returns:
      "fresh"    → 🟢 more than 3 days left
      "use_soon" → 🟡 1-3 days left
      "expired"  → 🔴 expired or today
      "unknown"  → no expiration date set
    """
    if expiration_date is None:
        return "unknown"

    today = date.today()
    days_left = (expiration_date - today).days

    if days_left > 3:
        return "fresh"
    elif days_left >= 1:
        return "use_soon"
    else:
        return "expired"


def get_freshness_emoji(status: str) -> str:
    return {
        "fresh":    "🟢",
        "use_soon": "🟡",
        "expired":  "🔴",
        "unknown":  "⚪",
    }.get(status, "⚪")


def days_until_expiry(expiration_date: Optional[date]) -> Optional[int]:
    if expiration_date is None:
        return None
    return (expiration_date - date.today()).days
