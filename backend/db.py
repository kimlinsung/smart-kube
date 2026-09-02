"""SQLite 数据存储：用户、操作日志、SSH 端口分配、Agent 会话上下文、实验。"""
from __future__ import annotations

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
                source_ip TEXT,
                created_at INTEGER
            )
            """
        )
        # 老库升级：审计日志补来源 IP，历史记录保留为空。
        cur.execute("PRAGMA table_info(audit_logs)")
        audit_cols = {r["name"] for r in cur.fetchall()}
        if "source_ip" not in audit_cols:
            cur.execute("ALTER TABLE audit_logs ADD COLUMN source_ip TEXT")
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
                created_at INTEGER,
                experiment_id INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        # 老库升级：chat_history 缺 experiment_id 时补上
        cur.execute("PRAGMA table_info(chat_history)")
        cols = {r["name"] for r in cur.fetchall()}
        if "experiment_id" not in cols:
            cur.execute("ALTER TABLE chat_history ADD COLUMN experiment_id INTEGER")

        # 老库升级：users 表补飞书绑定字段
        cur.execute("PRAGMA table_info(users)")
        ucols = {r["name"] for r in cur.fetchall()}
        for col, ddl in [
            ("feishu_open_id",   "ALTER TABLE users ADD COLUMN feishu_open_id TEXT"),
            ("feishu_union_id",  "ALTER TABLE users ADD COLUMN feishu_union_id TEXT"),
            ("name",             "ALTER TABLE users ADD COLUMN name TEXT"),
            ("email",            "ALTER TABLE users ADD COLUMN email TEXT"),
            ("avatar_url",       "ALTER TABLE users ADD COLUMN avatar_url TEXT"),
            # 飞书额外信息：英文名 / 手机 / 企业邮箱 / 大图头像 / 租户 key
            ("en_name",          "ALTER TABLE users ADD COLUMN en_name TEXT"),
            ("mobile",           "ALTER TABLE users ADD COLUMN mobile TEXT"),
            ("enterprise_email", "ALTER TABLE users ADD COLUMN enterprise_email TEXT"),
            ("avatar_big",       "ALTER TABLE users ADD COLUMN avatar_big TEXT"),
            ("tenant_key",       "ALTER TABLE users ADD COLUMN tenant_key TEXT"),
        ]:
            if col not in ucols:
                cur.execute(ddl)
        # 给 feishu_open_id 加唯一索引（NULL 不冲突，老用户不影响）
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_feishu_open_id "
            "ON users(feishu_open_id) WHERE feishu_open_id IS NOT NULL"
        )


def log_audit(user_id, username, action, detail="", source_ip=None):
    with cursor() as cur:
        cur.execute(
            "INSERT INTO audit_logs(user_id, username, action, detail, source_ip, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (user_id, username, action, str(detail)[:2000], source_ip, int(time.time())),
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


def search_audit_logs(
    user_id=None,
    username="",
    action="",
    keyword="",
    start_at=None,
    end_at=None,
    page=1,
    page_size=20,
):
    """筛选并分页读取审计日志，同时返回当前权限范围内的筛选项。"""
    page = max(1, int(page or 1))
    page_size = min(100, max(10, int(page_size or 20)))
    clauses: list[str] = []
    params: list[object] = []

    if user_id is not None:
        clauses.append("user_id=?")
        params.append(user_id)
    if username:
        clauses.append("username=?")
        params.append(username)
    if action:
        clauses.append("action=?")
        params.append(action)
    if keyword:
        pattern = f"%{keyword}%"
        clauses.append("(username LIKE ? OR action LIKE ? OR detail LIKE ? OR source_ip LIKE ?)")
        params.extend((pattern, pattern, pattern, pattern))
    if start_at is not None:
        clauses.append("created_at>=?")
        params.append(int(start_at))
    if end_at is not None:
        clauses.append("created_at<=?")
        params.append(int(end_at))

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    scope_where = " WHERE user_id=?" if user_id is not None else ""
    scope_params = (user_id,) if user_id is not None else ()

    with cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM audit_logs{where}", params)
        total = int(cur.fetchone()["c"])
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT * FROM audit_logs{where} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, page_size, offset),
        )
        logs = [dict(r) for r in cur.fetchall()]
        cur.execute(
            f"SELECT DISTINCT username FROM audit_logs{scope_where} "
            "WHERE username IS NOT NULL AND username!='' ORDER BY username"
            if scope_where == "" else
            "SELECT DISTINCT username FROM audit_logs WHERE user_id=? "
            "AND username IS NOT NULL AND username!='' ORDER BY username",
            scope_params,
        )
        usernames = [r["username"] for r in cur.fetchall()]
        cur.execute(
            f"SELECT DISTINCT action FROM audit_logs{scope_where} "
            + ("WHERE " if not scope_where else "AND ")
            + "action IS NOT NULL AND action!='' ORDER BY action",
            scope_params,
        )
        actions = [r["action"] for r in cur.fetchall()]

    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "facets": {"usernames": usernames, "actions": actions},
    }


def add_chat(user_id, role, content, experiment_id=None):
    with cursor() as cur:
        cur.execute(
            "INSERT INTO chat_history(user_id, role, content, created_at, experiment_id) VALUES(?,?,?,?,?)",
            (user_id, role, content, int(time.time()), experiment_id),
        )


def get_chat(user_id, limit=20, experiment_id=None):
    """读取用户最近 N 条对话上下文，按时间正序返回。
    experiment_id 指定时只返回该实验下的对话；不指定则返回该用户全部历史（兼容老用法）。"""
    with cursor() as cur:
        if experiment_id is None:
            cur.execute(
                "SELECT role, content, created_at FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
        else:
            cur.execute(
                "SELECT role, content, created_at FROM chat_history WHERE user_id=? AND experiment_id=? ORDER BY id DESC LIMIT ?",
                (user_id, experiment_id, limit),
            )
        rows = [dict(r) for r in cur.fetchall()]
    rows.reverse()
    return rows


def clear_chat(user_id, experiment_id=None):
    with cursor() as cur:
        if experiment_id is None:
            cur.execute("DELETE FROM chat_history WHERE user_id=?", (user_id,))
        else:
            cur.execute(
                "DELETE FROM chat_history WHERE user_id=? AND experiment_id=?",
                (user_id, experiment_id),
            )


# --------------------------------------------------------------------------------------
# 实验（一个 session = 一个 experiment）
# --------------------------------------------------------------------------------------

def create_experiment(user_id: int, name: str, description: str = "") -> dict:
    name = (name or "").strip() or "未命名实验"
    with cursor() as cur:
        cur.execute(
            "INSERT INTO experiments(user_id, name, description, created_at) VALUES(?,?,?,?)",
            (user_id, name, description, int(time.time())),
        )
        new_id = cur.lastrowid
        cur.execute("SELECT * FROM experiments WHERE id=?", (new_id,))
        return dict(cur.fetchone())


def get_experiment(exp_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT e.*, u.username AS owner_username FROM experiments e "
            "LEFT JOIN users u ON u.id = e.user_id WHERE e.id=?",
            (exp_id,),
        )
        r = cur.fetchone()
    return dict(r) if r else None


def list_experiments(user_id: int | None = None) -> list[dict]:
    """user_id=None 返回所有（管理员视图），否则只返回该用户的。"""
    with cursor() as cur:
        if user_id is None:
            cur.execute(
                "SELECT e.*, u.username AS owner_username FROM experiments e "
                "LEFT JOIN users u ON u.id = e.user_id ORDER BY e.id DESC"
            )
        else:
            cur.execute(
                "SELECT e.*, u.username AS owner_username FROM experiments e "
                "LEFT JOIN users u ON u.id = e.user_id WHERE e.user_id=? ORDER BY e.id DESC",
                (user_id,),
            )
        return [dict(r) for r in cur.fetchall()]


def delete_experiment(exp_id: int):
    """仅删 experiments 行和对应 chat_history。Pod 由 k8s_client 侧清理。"""
    with cursor() as cur:
        cur.execute("DELETE FROM chat_history WHERE experiment_id=?", (exp_id,))
        cur.execute("DELETE FROM experiments WHERE id=?", (exp_id,))


def ensure_default_experiment(user_id: int) -> int:
    """保证用户至少有一个实验，返回其 id（最早创建的那个）。"""
    with cursor() as cur:
        cur.execute(
            "SELECT id FROM experiments WHERE user_id=? ORDER BY id ASC LIMIT 1",
            (user_id,),
        )
        r = cur.fetchone()
        if r:
            return r["id"]
        cur.execute(
            "INSERT INTO experiments(user_id, name, description, created_at) VALUES(?,?,?,?)",
            (user_id, "默认实验", "首次登录自动创建", int(time.time())),
        )
        return cur.lastrowid
