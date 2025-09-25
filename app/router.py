# app/router.py
from flask import Blueprint, request, Response, jsonify
from sqlalchemy import text
import os
import logging

from .utils import normalize_wa, send_whatsapp_text
from .invoices import generate_invoice_pdf, send_invoice
from .admin_core import handle_admin_action
from .prospect import start_or_resume, _client_get, CLIENT_MENU
from .db import get_session
from . import booking, faq, client_nlp

router_bp = Blueprint("router", __name__)
log = logging.getLogger(__name__)
