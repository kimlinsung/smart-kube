"""HTTP-aware audit writer."""
from __future__ import annotations

from . import db
from .request_meta import client_ip


def log(user_id, username, action, detail="", source_ip=None):
    db.log_audit(
        user_id,
        username or "unknown",
        action,
        detail,
        source_ip=source_ip or client_ip(),
    )
