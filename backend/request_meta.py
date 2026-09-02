"""Request metadata helpers used by audit logging."""
from __future__ import annotations

import ipaddress

from flask import has_request_context, request


def _normalise_ip(value: str | None) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return "unknown"
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return "unknown"


def client_ip() -> str:
    """Return a validated client IP without trusting arbitrary proxy headers.

    Production runs behind a same-host reverse proxy. Forwarding headers are
    considered only when the direct peer is loopback; direct clients cannot
    spoof their address by sending X-Forwarded-For themselves.
    """
    if not has_request_context():
        return "unknown"

    peer = _normalise_ip(request.remote_addr)
    try:
        peer_is_loopback = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        peer_is_loopback = False

    if peer_is_loopback:
        real_ip = _normalise_ip(request.headers.get("X-Real-IP"))
        if real_ip != "unknown":
            return real_ip

        # With one trusted local proxy, the right-most forwarded address is
        # the value added by that proxy and cannot be supplied by the client.
        forwarded = request.headers.get("X-Forwarded-For", "")
        for value in reversed(forwarded.split(",")):
            forwarded_ip = _normalise_ip(value)
            if forwarded_ip != "unknown":
                return forwarded_ip

    return peer
