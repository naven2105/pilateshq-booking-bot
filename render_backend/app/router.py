# app/router.py
"""
Compatibility shim.

⚠️ Deprecated: the main router has been split into app/router_webhook.py 
(and other modules). This file only re-exports the router_bp blueprint
for backward compatibility.

Please update imports:
    from app.router_webhook import router_bp
"""

import logging
from .router_webhook import router_bp

log = logging.getLogger(__name__)
log.warning("⚠️ [DEPRECATED] app.router is deprecated; use app.router_webhook instead.")
