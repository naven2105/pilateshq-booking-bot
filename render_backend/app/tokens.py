"""
tokens.py – Secure, Expiring Link Utility
────────────────────────────────────────────
Generates and verifies short-lived signed tokens
for secure invoice links.
────────────────────────────────────────────
"""

import os, time
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# ── Secret key from env ─────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
SALT = "pilateshq-invoice"

# ── Serializer setup ────────────────────────────────────────────────
def _serializer():
    return URLSafeTimedSerializer(SECRET_KEY, salt=SALT)

# ── Generate secure token ───────────────────────────────────────────
def generate_invoice_token(client_name: str, invoice_id: str) -> str:
    """Return signed token encoding client + invoice id."""
    data = {"client": client_name, "invoice": invoice_id, "ts": int(time.time())}
    return _serializer().dumps(data)

# ── Verify token ───────────────────────────────────────────────────
def verify_invoice_token(token: str, max_age: int = 172800) -> dict:
    """
    Returns decoded data if valid and not expired.
    Default expiry = 48 hours (172 800 sec).
    """
    try:
        return _serializer().loads(token, max_age=max_age)
    except SignatureExpired:
        return {"ok": False, "error": "Expired link"}
    except BadSignature:
        return {"ok": False, "error": "Invalid link"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
