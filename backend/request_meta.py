"""Request metadata helpers used by audit logging."""
from __future__ import annotations

import ipaddress

from flask import has_request_context, request

from .config import FLASK_CONF


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

    Forwarding headers are considered only when the direct peer is loopback
    or explicitly listed as a trusted reverse proxy. Direct clients cannot
    spoof their address by sending X-Forwarded-For themselves.
    """
    if not has_request_context():
        return "unknown"

    peer = _normalise_ip(request.remote_addr)
    try:
        peer_is_loopback = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        peer_is_loopback = False

    configured_proxies = FLASK_CONF.get("trusted_proxy_ips", [])
    if isinstance(configured_proxies, str):
        configured_proxies = [configured_proxies]
    trusted_proxies = {
        _normalise_ip(value)
        for value in configured_proxies
        if _normalise_ip(value) != "unknown"
    }

    if peer_is_loopback or peer in trusted_proxies:
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
