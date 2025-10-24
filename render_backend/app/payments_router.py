"""
payments_router.py – Phase 12
────────────────────────────────────────────
Logs client payments from WhatsApp-style messages and
auto-matches them to invoices via the GAS Web App.

Endpoints:
 • POST /payments/log
    - Body (free text): {"text": "Fatima Khan paid R1,000 on 24 Oct"}
    - Body (structured): {"client_name":"Fatima Khan","amount":1000,"handled_by":"Nadine","source":"Bank"}
 • GET  /payments/health
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
# Re-use the same GAS endpoint you use for invoices (now supports append_payment)
GAS_INVOICE_URL = os.getenv("GAS_INVOICE_URL", "")
TZ_NAME = os.getenv("TZ_NAME", "Africa/Johannesburg")

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
        \d{1,3}(?:[ ,]\d{3})*(?:[.,]\d{2})? |  # 1,000.00 / 1 000,00 / 1000.00
        \d+(?:[.,]\d{2})?                       # 1000 / 1000.00
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
    """Normalize South African currency strings to float."""
    if raw is None:
        return 0.0
    s = raw.strip()
    # unify thousands/decimal: drop spaces/commas as thousand seps, keep final dot/comma as decimal
    # heuristic: if both separators present, last one is decimal; otherwise treat '.' as decimal
    s = s.replace(" ", "")
    if "," in s and "." in s:
        # remove thousand separator (assume comma thousands, dot decimal OR vice versa)
        if s.rfind(",") > s.rfind("."):
            # comma after dot → comma decimal, dot thousands
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            # dot decimal, comma thousands
            s = s.replace(",", "")
    else:
        # single type of separator
        if "," in s:
            # assume comma decimal if only one comma and there are exactly 2 digits after
            parts = s.split(",")
            if len(parts[-1]) in (1,2):
                s = ".".join(parts)
            else:
                s = "".join(parts)  # treat commas as thousands
    s = s.lstrip("Rr")
    try:
        return float(s)
    except ValueError:
        return 0.0

def _parse_free_text(text: str) -> Tuple[Optional[str], Optional[float], Optional[str]]:
    """
    Parse "Name paid R1000 [on 24 Oct]" → (name, amount, date_str)
    Returns (client_name, amount_float, date_text or None)
    """
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
    """Unified POST to GAS with a single retry on transient failure."""
    if not GAS_INVOICE_URL:
        return {"ok": False, "error": "Missing GAS_INVOICE_URL"}
    try:
        r = requests.post(GAS_INVOICE_URL, json=payload, timeout=timeout)
        if r.ok:
            return r.json()
        log.error(f"GAS HTTP {r.status_code}: {r.text[:200]}")
        # quick retry once for 5xx
        if 500 <= r.status_code < 600:
            time.sleep(2)
            r2 = requests.post(GAS_INVOICE_URL, json=payload, timeout=timeout)
            return r2.json() if r2.ok else {"ok": False, "error": f"GAS HTTP {r2.status_code}"}
        return {"ok": False, "error": f"GAS HTTP {r.status_code}"}
    except Exception as e:
        log.error(f"GAS POST failed: {e}")
        # retry once on network error
        try:
            time.sleep(2)
            r2 = requests.post(GAS_INVOICE_URL, json=payload, timeout=timeout)
            return r2.json() if r2.ok else {"ok": False, "error": f"GAS HTTP {r2.status_code}"}
        except Exception as e2:
            return {"ok": False, "error": str(e2)}

def _mk_date_iso(date_text: Optional[str]) -> str:
    """Convert loose date text to ISO yyyy-mm-dd in TZ_NAME when possible; else today."""
    try:
        if not date_text:
            now = datetime.now()
            return now.strftime("%Y-%m-%d")
        # very lightweight parse: accept d[d] Mon or d[d]/m[m]/yyyy etc.
        dt_text = date_text.strip()
        # Try common formats
        for fmt in ("%d %b %Y", "%d %b", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(dt_text, fmt)
                # if year omitted, assume current year
                if fmt in ("%d %b",):
                    dt = dt.replace(year=datetime.now().year)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        # fallback: today
        return datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────
@bp.route("/payments/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "Payments Router",
        "gas_url_set": bool(GAS_INVOICE_URL),
        "timezone": TZ_NAME,
        "endpoints": ["/payments/log", "/payments/health"]
    }), 200

@bp.route("/payments/log", methods=["POST"])
def payments_log():
    """
    Accepts:
      A) Free text → {"text":"Fatima Khan paid R1,000 on 24 Oct"}
      B) Structured → {"client_name":"Fatima Khan","amount":1000,"source":"Bank","handled_by":"Nadine","date":"2025-10-24"}

    Calls GAS: {"action":"append_payment", ...} and relays the JSON result.
    """
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

    # If free text present, parse it
    if text and (not client_name or not amount):
        name, amt, dtxt = _parse_free_text(text)
        if name:
            client_name = client_name or name
        if amt:
            amount = amount or amt
        if dtxt and not date_str:
            date_str = dtxt

    # Basic validation
    if not client_name:
        return jsonify({"ok": False, "error": "Missing client_name (or parse failed)"}), 400
    try:
        amount = float(amount)
    except Exception:
        return jsonify({"ok": False, "error": "Missing/invalid amount"}), 400
    if amount <= 0:
        return jsonify({"ok": False, "error": "Amount must be > 0"}), 400

    # Normalize date to ISO for logging (GAS computes its own timestamp; we pass for message context only if you extend later)
    iso_date = _mk_date_iso(date_str)

    payload = {
        "action": "append_payment",
        "client_name": client_name,
        "amount": amount,
        "source": source,
        "handled_by": handled_by,
        # date is currently informational; GAS uses its own server timestamp.
        # If you later want GAS to accept client-specified dates, add support in appendPayment_.
    }

    gas_resp = _post_to_gas(payload)
    ok = bool(gas_resp.get("ok"))
    status_code = 200 if ok else 502

    # Augment response with the parsed/normalized input for observability
    return jsonify({
        "ok": ok,
        "client_name": client_name,
        "amount": amount,
        "date": iso_date,
        "source": source,
        "handled_by": handled_by,
        "gas_result": gas_resp
    }), status_code
