"""基于持久 WebSocket 的单进程在线状态注册表。"""
from __future__ import annotations

import json
import logging
import threading

from flask import session

from . import db

log = logging.getLogger(__name__)

_lock = threading.RLock()
_connections: dict[int, set[object]] = {}
_admin_connections: set[object] = set()


def online_user_ids() -> set[int]:
    with _lock:
        return {user_id for user_id, sockets in _connections.items() if sockets}


def _send(ws, payload: dict) -> bool:
    try:
        ws.send(json.dumps(payload, ensure_ascii=False))
        return True
    except Exception:
        return False


def _broadcast(payload: dict):
    with _lock:
        targets = list(_admin_connections)
    failed = [ws for ws in targets if not _send(ws, payload)]
    if failed:
        with _lock:
            for ws in failed:
                _admin_connections.discard(ws)


def _connect(ws, user: dict):
    user_id = int(user["id"])
    with _lock:
        sockets = _connections.setdefault(user_id, set())
        became_online = not sockets
        sockets.add(ws)
        if user["role"] == "admin":
            _admin_connections.add(ws)
        snapshot = sorted(user_id for user_id, active in _connections.items() if active)

    if user["role"] == "admin":
        _send(ws, {"type": "presence_snapshot", "online_user_ids": snapshot})
    if became_online:
        _broadcast({"type": "presence", "user_id": user_id, "online": True})


def _disconnect(ws, user: dict):
    user_id = int(user["id"])
    with _lock:
        sockets = _connections.get(user_id)
        if sockets:
            sockets.discard(ws)
            if not sockets:
                _connections.pop(user_id, None)
                became_offline = True
            else:
                became_offline = False
        else:
            became_offline = False
        _admin_connections.discard(ws)

    if became_offline:
        _broadcast({"type": "presence", "user_id": user_id, "online": False})


def register(sock):
    @sock.route("/ws/presence")
    def presence_socket(ws):
        user_id = session.get("user_id")
        if not user_id:
            ws.close()
            return
        with db.cursor() as cur:
            cur.execute("SELECT id, username, role FROM users WHERE id=?", (user_id,))
            row = cur.fetchone()
        if not row:
            ws.close()
            return
        user = dict(row)
        _connect(ws, user)
        try:
            while ws.receive() is not None:
                pass
        except Exception as exc:
            log.debug("presence websocket closed: %s", exc)
        finally:
            _disconnect(ws, user)
