# app/settings.py

# ──────────────────────────────────────────────────────────────
# Central pricing & capacity settings
# Update these values when prices or class capacity change
# ──────────────────────────────────────────────────────────────

PRICING_RULES = {
    "single": 300,   # Single session (1 person)
    "duo": 250,      # Duo session (2 people)
    "group": 180,    # Group session (3 up to GROUP_MAX_CAPACITY)
}

# Max number of clients allowed in a group session
# (Change if new reformers are bought or sold)
GROUP_MAX_CAPACITY = 6
