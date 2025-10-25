"""
payments_router.py – Phase 14 (Final)
────────────────────────────────────────────
Logs client payments from WhatsApp-style messages and
auto-matches them to invoices via the GAS Web App.

Adds WhatsApp confirmation to Nadine on success.
────────────────────────────────────────────
"""

import os
import re
import json
import time
import logging
from datetime import datetime
from typing import Optional, Tuple
import requests
from flask import Blueprint, request, jsonify

# ── Blueprint & Logger ────────────────────────────────────────
bp = Blueprint("payments_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment ───────────────────────────────────────────────
GAS_INVOICE_URL = os.getenv("GAS_INVOICE_URL", "")
TZ_NAME = os.getenv("TZ_NAME", "Africa/Johannesburg")
NADINE_WA = os.getenv("NADINE_WA", "")
TPL_ADMIN_ALERT = "admin_generic_alert_us"

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
AMOUNT_RE = re.compile(
    r"""
    (?:
        R|ZAR|\brand[s]?\b
    )?                           # optional currency indicator
    \s*
    (?P<amount>
        \d{1,3}(?:[ ,]\d{3})*(?:[.,]\d{2})? |
        \d+(?:[.,]\d{2})?
    )
    """,
    re.IGNORECASE | re.VERBOSE
)

PAID_RE = re.compile(
    r"""
    ^\s*
    (?P<name>.+?)
    \s+paid\s+
    (?P<currency>R|ZAR|rand[s]?)?\s*
    (?P<amount>\d{1,3}(?:[ ,]\d{3})*(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)
    (?:\s+on\s+(?P<date>.+))?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE
)

def _norm_amount(raw: str) -> float:
    if raw is None:
        return 0.0
    s = raw.strip().replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        s = ".".join(parts) if len(parts[-1]) in (1, 2) else "".join(parts)
    s = s.lstrip("Rr")
    try:
        return float(s)
    except ValueError:
        return 0.0

def _parse_free_text(text: str) -> Tuple[Optional[str], Optional[float], Optional[str]]:
    if not text:
        return None, None, None
    m = PAID_RE.match(text.strip())
    if not m:
        return None, None, None
    name = m.group("name").strip()
    amount = _norm_amount(m.group("amount"))
    date_text = m.group("date").strip() if m.group("date") else None
    return name, amount, date_text

def _post_to_gas(payload: dict, timeout: int = 20) -> dict:
    if not GAS_INVOICE_URL:
        return {"ok": False, "error": "Missing GAS_INVOICE_URL"}
    try:
        r = requests.post(GAS_INVOICE_URL, json=payload, timeout=timeout)
        if r.ok:
            return r.json()
        log.error(f"GAS HTTP {r.status_code}: {r.text[:200]}")
        if 500 <= r.status_code < 600:
            time.sleep(2)
            r2 = requests.post(GAS_INVOICE_URL, json=payload, timeout=timeout)
            return r2.json() if r2.ok else {"ok": False, "error": f"GAS HTTP {r2.status_code}"}
        return {"ok": False, "error": f"GAS HTTP {r.status_code}"}
    except Exception as e:
        log.error(f"GAS POST failed: {e}")
        try:
            time.sleep(2)
            r2 = requests.post(GAS_INVOICE_URL, json=payload, timeout=timeout)
            return r2.json() if r2.ok else {"ok": False, "error": f"GAS HTTP {r2.status_code}"}
        except Exception as e2:
            return {"ok": False, "error": str(e2)}

def _mk_date_iso(date_text: Optional[str]) -> str:
    try:
        if not date_text:
            return datetime.now().strftime("%Y-%m-%d")
        dt_text = date_text.strip()
        for fmt in ("%d %b %Y", "%d %b", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(dt_text, fmt)
                if fmt in ("%d %b",):
                    dt = dt.replace(year=datetime.now().year)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────
@bp.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "Payments Router",
        "gas_url_set": bool(GAS_INVOICE_URL),
        "timezone": TZ_NAME,
        "endpoints": ["/payments/log", "/payments/health"]
    }), 200

@bp.route("/log", methods=["POST"])
def payments_log():
    """Accepts free-text or structured JSON, logs to GAS, and notifies Nadine."""
    try:
        data = request.get_json(force=True, silent=False) or {}
    except Exception:
        return jsonify({"ok": False, "error": "Invalid JSON"}), 400

    text = str(data.get("text", "")).strip()
    client_name = (data.get("client_name") or "").strip()
    amount = data.get("amount")
    handled_by = (data.get("handled_by") or "Nadine").strip()
    source = (data.get("source") or "Bank").strip()
    date_str = (data.get("date") or "").strip()

    if text and (not client_name or not amount):
        name, amt, dtxt = _parse_free_text(text)
        if name:
            client_name = client_name or name
        if amt:
            amount = amount or amt
        if dtxt and not date_str:
            date_str = dtxt

    if not client_name:
        return jsonify({"ok": False, "error": "Missing client_name (or parse failed)"}), 400
    try:
        amount = float(amount)
    except Exception:
        return jsonify({"ok": False, "error": "Missing/invalid amount"}), 400
    if amount <= 0:
        return jsonify({"ok": False, "error": "Amount must be > 0"}), 400

    iso_date = _mk_date_iso(date_str)
    payload = {
        "action": "append_payment",
        "client_name": client_name,
        "amount": amount,
        "source": source,
        "handled_by": handled_by
    }

    gas_resp = _post_to_gas(payload)
    ok = bool(gas_resp.get("ok"))
    status_code = 200 if ok else 502

    # ✅ WhatsApp confirmation to Nadine if payment logged successfully
    if ok:
        summary = gas_resp.get("message") or f"{client_name} payment logged"
        notify_text = f"✅ {summary}"
        try:
            from .utils import send_safe_message
            send_safe_message(
                to=NADINE_WA,
                is_template=True,
                template_name=TPL_ADMIN_ALERT,
                variables=[notify_text],
                label="payment_confirmation"
            )
        except Exception as e:
            log.error(f"WhatsApp notify failed: {e}")

    return jsonify({
        "ok": ok,
        "client_name": client_name,
        "amount": amount,
        "date": iso_date,
        "source": source,
        "handled_by": handled_by,
        "gas_result": gas_resp
    }), status_code
