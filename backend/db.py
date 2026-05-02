"""SQLite 数据存储：用户、操作日志、SSH 端口分配、Agent 会话上下文。"""
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

from .config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "smartkube.db")
_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


@contextmanager
def cursor():
    with _lock:
        c = _conn()
        try:
            yield c.cursor()
            c.commit()
        finally:
            c.close()


def init_db():
    """初始化全部表结构。"""
    with cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                action TEXT,
                detail TEXT,
                created_at INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ssh_ports (
                port INTEGER PRIMARY KEY,
                pod_name TEXT,
                user_id INTEGER,
                allocated_at INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                created_at INTEGER
            )
            """
        )


def log_audit(user_id, username, action, detail=""):
    with cursor() as cur:
        cur.execute(
            "INSERT INTO audit_logs(user_id, username, action, detail, created_at) VALUES(?,?,?,?,?)",
            (user_id, username, action, str(detail)[:2000], int(time.time())),
        )


def get_audit_logs(user_id=None, limit=200):
    with cursor() as cur:
        if user_id is None:
            cur.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
        else:
            cur.execute(
                "SELECT * FROM audit_logs WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
        return [dict(r) for r in cur.fetchall()]


def add_chat(user_id, role, content):
    with cursor() as cur:
        cur.execute(
            "INSERT INTO chat_history(user_id, role, content, created_at) VALUES(?,?,?,?)",
            (user_id, role, content, int(time.time())),
        )


def get_chat(user_id, limit=20):
    """读取用户最近 N 条对话上下文，按时间正序返回。"""
    with cursor() as cur:
        cur.execute(
            "SELECT role, content FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
    rows.reverse()
    return rows


def clear_chat(user_id):
    with cursor() as cur:
        cur.execute("DELETE FROM chat_history WHERE user_id=?", (user_id,))
