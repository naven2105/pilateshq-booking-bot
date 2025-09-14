# app/config.py
import os

# ── Helpers ───────────────────────────────────────────────────────────────────
def _canon_wa(s: str) -> str:
    """
    Canonicalise a WhatsApp phone number to digits-only E.164 (no '+').
    Examples:
      '+27 62-759-7357' -> '27627597357'
      ' (27)627-599-357 ' -> '27627599357'  (digits only)
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
# Environment:
#   ADMIN_NUMBERS: comma-separated list, any format is OK (e.g. "+2762..., 2762..., 27 62 ...")
#   NADINE_WA    : optional single number; if set, it will be merged below
_raw_admins = _split_csv(os.environ.get("ADMIN_NUMBERS", ""))
_nadine_wa  = os.environ.get("NADINE_WA", "").strip()

if _nadine_wa:
    _raw_admins.append(_nadine_wa)

# Canonicalise to digits-only, then de-duplicate
_ADMIN_SET = { _canon_wa(n) for n in _raw_admins if _canon_wa(n) }
ADMIN_NUMBERS = sorted(_ADMIN_SET)  # e.g. ["27627597357", "27843131635"]

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── Local timezone for schedule logic (PostgreSQL AT TIME ZONE) ─────────────
TZ_NAME = os.environ.get("TZ_NAME", "Africa/Johannesburg")

# ── Templates for outbound messages (outside 24h window) ─────────────────────
# Default admin template setup (names must match your WhatsApp Manager)
ADMIN_TEMPLATE_NAME = os.environ.get("ADMIN_TEMPLATE_NAME", "admin_update")

# Language codes:
#  - Admin templates are English (South Africa) in your account → "en_ZA"
#  - Client templates vary; see usage in reminder modules
ADMIN_TEMPLATE_LANG = os.environ.get("ADMIN_TEMPLATE_LANG", "en_ZA")

# Client template defaults (used in client_reminders.py; override via env if needed)
CLIENT_TEMPLATE_TOMORROW       = os.environ.get("CLIENT_TEMPLATE_TOMORROW", "session_tomorrow")
CLIENT_TEMPLATE_TOMORROW_LANG  = os.environ.get("CLIENT_TEMPLATE_TOMORROW_LANG", "en_US")
CLIENT_TEMPLATE_NEXT_HOUR      = os.environ.get("CLIENT_TEMPLATE_NEXT_HOUR", "session_next_hour")
CLIENT_TEMPLATE_NEXT_HOUR_LANG = os.environ.get("CLIENT_TEMPLATE_NEXT_HOUR_LANG", "en")
CLIENT_TEMPLATE_WEEKLY         = os.environ.get("CLIENT_TEMPLATE_WEEKLY", "weekly_template_message")
CLIENT_TEMPLATE_WEEKLY_LANG    = os.environ.get("CLIENT_TEMPLATE_WEEKLY_LANG", "en")

# ── Flags ────────────────────────────────────────────────────────────────────
# If True → try to use templates when possible, else fallback to plain text
USE_TEMPLATES = os.environ.get("USE_TEMPLATES", "1") in ("1", "true", "True")

# Default template language code for WhatsApp Cloud API (fallback; module-level overrides take precedence)
TEMPLATE_LANG = os.environ.get("TEMPLATE_LANG", "en")
