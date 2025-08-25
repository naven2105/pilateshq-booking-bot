# app/config.py
import os

def _env(name: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        # Don't crash at import-time; log to stdout so Render logs show it.
        print(f"[CONFIG] Missing required env var: {name}")
    return val

# Core
VERIFY_TOKEN     = _env("VERIFY_TOKEN", "your_verify_token_here")
ACCESS_TOKEN     = _env("ACCESS_TOKEN", required=True)             # WhatsApp Permanent Token
PHONE_NUMBER_ID  = _env("PHONE_NUMBER_ID", required=True)          # e.g. 802833389569115
DATABASE_URL     = _env("DATABASE_URL", required=True)             # Render Postgres URL
NADINE_WA        = _env("NADINE_WA", "27843131635")                # e.g. 27843131635 (no +)

# Logging
LOG_LEVEL        = (_env("LOG_LEVEL", "INFO") or "INFO").upper()

# Meta Graph
GRAPH_API_VERSION = _env("GRAPH_API_VERSION", "v21.0")
GRAPH_URL         = (
    f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    if PHONE_NUMBER_ID else ""
)

# Optional flags (future-proofing)
FEATURE_WELLNESS  = (_env("FEATURE_WELLNESS", "1") == "1")
FEATURE_ONBOARD   = (_env("FEATURE_ONBOARD", "1") == "1")

def config_summary() -> dict:
    """Useful for debugging (avoid printing secrets)."""
    return {
        "VERIFY_TOKEN_set": bool(VERIFY_TOKEN),
        "ACCESS_TOKEN_set": bool(ACCESS_TOKEN),
        "PHONE_NUMBER_ID": PHONE_NUMBER_ID,
        "DATABASE_URL_set": bool(DATABASE_URL),
        "NADINE_WA": NADINE_WA,
        "LOG_LEVEL": LOG_LEVEL,
        "GRAPH_URL_ok": bool(GRAPH_URL),
        "GRAPH_API_VERSION": GRAPH_API_VERSION,
        "FEATURE_WELLNESS": FEATURE_WELLNESS,
        "FEATURE_ONBOARD": FEATURE_ONBOARD,
    }
