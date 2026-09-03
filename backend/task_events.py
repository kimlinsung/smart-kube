"""Realtime execution-task updates over authenticated WebSockets."""
from __future__ import annotations

import json
import logging
import threading

from flask import session

from . import db

log = logging.getLogger(__name__)

_lock = threading.RLock()
_connections: dict[int, set[object]] = {}


def _send(ws, payload: dict) -> bool:
    try:
        ws.send(json.dumps(payload, ensure_ascii=False))
        return True
    except Exception:
        return False


def publish(user_id: int, payload: dict):
    with _lock:
        targets = list(_connections.get(int(user_id), set()))
    failed = [ws for ws in targets if not _send(ws, payload)]
    if failed:
        with _lock:
            sockets = _connections.get(int(user_id), set())
            for ws in failed:
                sockets.discard(ws)


def publish_task(task_id: str):
    task = db.get_execution_task(task_id)
    if not task:
        return
    publish(task["user_id"], {"type": "task_update", "task": task})
    if not task.get("experiment_id"):
        return
    workspace_update = {
        "id": task["id"],
        "experiment_id": task["experiment_id"],
        "status": task["status"],
        "progress": task["progress"],
        "updated_at": task["updated_at"],
        "metadata": {
            "workspace_id": (task.get("metadata") or {}).get("workspace_id"),
        },
    }
    for collaborator_id in db.list_experiment_collaborator_user_ids(task["experiment_id"]):
        publish(collaborator_id, {"type": "workspace_task_update", "task": workspace_update})


def register(sock):
    @sock.route("/ws/tasks")
    def task_socket(ws):
        user_id = session.get("user_id")
        if not user_id:
            ws.close()
            return
        with db.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id=?", (user_id,))
            if not cur.fetchone():
                ws.close()
                return

        user_id = int(user_id)
        with _lock:
            _connections.setdefault(user_id, set()).add(ws)
        _send(ws, {
            "type": "task_snapshot",
            "tasks": db.list_execution_tasks(user_id, limit=30),
        })
        try:
            while ws.receive() is not None:
                pass
        except Exception as exc:
            log.debug("task websocket closed: %s", exc)
        finally:
            with _lock:
                sockets = _connections.get(user_id)
                if sockets:
                    sockets.discard(ws)
                    if not sockets:
                        _connections.pop(user_id, None)
