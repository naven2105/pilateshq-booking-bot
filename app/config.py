# app/config.py
import os, logging

# ── Helpers ───────────────────────────────────────────────────────────────────
def _canon_wa(s: str) -> str:
    """
    Canonicalise a WhatsApp phone number to digits-only E.164 (no '+').
    """
    if not s:
        return ""
    return "".join(ch for ch in s if ch.isdigit())

def _split_csv(env_val: str) -> list[str]:
    return [x.strip() for x in (env_val or "").split(",") if x.strip()]

# ── Meta / WhatsApp Cloud API ────────────────────────────────────────────────
ACCESS_TOKEN     = os.environ.get("ACCESS_TOKEN", "")
PHONE_NUMBER_ID  = os.environ.get("PHONE_NUMBER_ID", "")  # e.g. "802833389569115"
VERIFY_TOKEN     = os.environ.get("VERIFY_TOKEN", "testtoken")

# Graph endpoint (version can be bumped without code changes)
GRAPH_VER = os.environ.get("GRAPH_VER", "v21.0")
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VER}/{PHONE_NUMBER_ID}/messages"

# ── Admin numbers ────────────────────────────────────────────────────────────
_raw_admins = _split_csv(os.environ.get("ADMIN_NUMBERS", ""))
_nadine_wa  = os.environ.get("NADINE_WA", "").strip()

if _nadine_wa:
    _raw_admins.append(_nadine_wa)

_ADMIN_SET = { _canon_wa(n) for n in _raw_admins if _canon_wa(n) }
ADMIN_NUMBERS = sorted(_ADMIN_SET)  # e.g. ["27627597357", "27843131635"]

# Expose Nadine’s WA separately (fallback = first admin)
NADINE_WA = _canon_wa(_nadine_wa) if _nadine_wa else (ADMIN_NUMBERS[0] if ADMIN_NUMBERS else "")

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── Local timezone ───────────────────────────────────────────────────────────
TZ_NAME = os.environ.get("TZ_NAME", "Africa/Johannesburg")

# ── Templates ────────────────────────────────────────────────────────────────
ADMIN_TEMPLATE_NAME = os.environ.get("ADMIN_TEMPLATE_NAME", "admin_update")
ADMIN_TEMPLATE_LANG = os.environ.get("ADMIN_TEMPLATE_LANG", "en_ZA")

CLIENT_TEMPLATE_TOMORROW       = os.environ.get("CLIENT_TEMPLATE_TOMORROW", "session_tomorrow")
CLIENT_TEMPLATE_TOMORROW_LANG  = os.environ.get("CLIENT_TEMPLATE_TOMORROW_LANG", "en_US")
CLIENT_TEMPLATE_NEXT_HOUR      = os.environ.get("CLIENT_TEMPLATE_NEXT_HOUR", "session_next_hour")
CLIENT_TEMPLATE_NEXT_HOUR_LANG = os.environ.get("CLIENT_TEMPLATE_NEXT_HOUR_LANG", "en")
CLIENT_TEMPLATE_WEEKLY         = os.environ.get("CLIENT_TEMPLATE_WEEKLY", "weekly_template_message")
CLIENT_TEMPLATE_WEEKLY_LANG    = os.environ.get("CLIENT_TEMPLATE_WEEKLY_LANG", "en")

# ── Flags ────────────────────────────────────────────────────────────────────
USE_TEMPLATES = os.environ.get("USE_TEMPLATES", "1") in ("1", "true", "True")
TEMPLATE_LANG = os.environ.get("TEMPLATE_LANG", "en")

# ── Startup logging ──────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
logger.info(f"[CONFIG] Loaded ADMIN_NUMBERS={ADMIN_NUMBERS}, NADINE_WA={NADINE_WA}")
