"""SQLite 数据存储：用户、操作日志、SSH 端口分配、Agent 会话上下文、实验。"""
from __future__ import annotations

import os
import json
import secrets
import sqlite3
import threading
import time
import uuid
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS experiment_collaborators (
                experiment_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                added_by INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (experiment_id, user_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS experiment_shares (
                experiment_id INTEGER PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                created_by INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS script_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                experiment_id INTEGER,
                original_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_tasks (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                experiment_id INTEGER,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT,
                progress INTEGER NOT NULL DEFAULT 0,
                result TEXT,
                error TEXT,
                metadata TEXT,
                created_at INTEGER NOT NULL,
                started_at INTEGER,
                updated_at INTEGER NOT NULL,
                finished_at INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                content TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_workspaces (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                experiment_id INTEGER NOT NULL UNIQUE,
                name TEXT NOT NULL,
                goal TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                resource_spec TEXT NOT NULL,
                config_json TEXT,
                schedule_json TEXT,
                analysis_json TEXT,
                report_md TEXT,
                retries INTEGER NOT NULL DEFAULT 0,
                resources_reclaimed INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                finished_at INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_workspace_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                original_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                content_type TEXT,
                artifact_type TEXT NOT NULL DEFAULT 'input',
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute("PRAGMA table_info(paper_workspace_files)")
        paper_file_cols = {r["name"] for r in cur.fetchall()}
        if "artifact_type" not in paper_file_cols:
            cur.execute(
                "ALTER TABLE paper_workspace_files "
                "ADD COLUMN artifact_type TEXT NOT NULL DEFAULT 'input'"
            )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_workspace_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id TEXT NOT NULL,
                phase TEXT NOT NULL,
                event_type TEXT NOT NULL,
                content TEXT,
                data TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_script_files_owner "
            "ON script_files(user_id, experiment_id, id DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_execution_tasks_owner "
            "ON execution_tasks(user_id, experiment_id, created_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_experiment_collaborators_user "
            "ON experiment_collaborators(user_id, experiment_id)"
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_experiment_shares_token "
            "ON experiment_shares(token)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_events_task "
            "ON task_events(task_id, id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_workspaces_owner "
            "ON paper_workspaces(user_id, created_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_workspace_files_workspace "
            "ON paper_workspace_files(workspace_id, id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_workspace_events_workspace "
            "ON paper_workspace_events(workspace_id, id)"
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
# 上传脚本与可恢复执行任务
# --------------------------------------------------------------------------------------

def create_script_file(user_id, experiment_id, original_name, stored_path, size=0):
    now = int(time.time())
    with cursor() as cur:
        cur.execute(
            "INSERT INTO script_files(user_id, experiment_id, original_name, stored_path, size, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (user_id, experiment_id, original_name, stored_path, int(size or 0), now),
        )
        file_id = cur.lastrowid
        cur.execute("SELECT * FROM script_files WHERE id=?", (file_id,))
        return dict(cur.fetchone())


def get_script_file(file_id, user_id=None):
    clauses = ["id=?"]
    params = [file_id]
    if user_id is not None:
        clauses.append("user_id=?")
        params.append(user_id)
    with cursor() as cur:
        cur.execute(
            "SELECT id, user_id, experiment_id, original_name, size, created_at "
            f"FROM script_files WHERE {' AND '.join(clauses)}",
            params,
        )
        row = cur.fetchone()
    return dict(row) if row else None


def get_script_file_internal(file_id, user_id=None):
    clauses = ["id=?"]
    params = [file_id]
    if user_id is not None:
        clauses.append("user_id=?")
        params.append(user_id)
    with cursor() as cur:
        cur.execute(f"SELECT * FROM script_files WHERE {' AND '.join(clauses)}", params)
        row = cur.fetchone()
    return dict(row) if row else None


def get_latest_script_file(user_id, experiment_id=None):
    if experiment_id is None:
        query = "SELECT * FROM script_files WHERE user_id=? ORDER BY id DESC LIMIT 1"
        params = (user_id,)
    else:
        query = (
            "SELECT * FROM script_files WHERE user_id=? AND experiment_id=? "
            "ORDER BY id DESC LIMIT 1"
        )
        params = (user_id, experiment_id)
    with cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
    if not row:
        return None
    item = dict(row)
    item.pop("stored_path", None)
    return item


def create_execution_task(user_id, experiment_id, kind, title, detail="", metadata=None):
    now = int(time.time())
    task_id = uuid.uuid4().hex
    metadata_text = json.dumps(metadata or {}, ensure_ascii=False)
    with cursor() as cur:
        cur.execute(
            "INSERT INTO execution_tasks("
            "id,user_id,experiment_id,kind,status,title,detail,progress,metadata,created_at,updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, user_id, experiment_id, kind, "queued", title, detail, 0, metadata_text, now, now),
        )
        cur.execute(
            "INSERT INTO task_events(task_id,event_type,content,created_at) VALUES(?,?,?,?)",
            (task_id, "queued", detail or "任务已进入队列", now),
        )
    return get_execution_task(task_id, user_id=user_id)


def update_execution_task(task_id, **changes):
    allowed = {
        "status", "title", "detail", "progress", "result", "error",
        "started_at", "finished_at", "metadata",
    }
    updates = []
    params = []
    for key, value in changes.items():
        if key not in allowed:
            continue
        if key == "metadata" and not isinstance(value, str):
            value = json.dumps(value or {}, ensure_ascii=False)
        if key == "progress":
            value = min(100, max(0, int(value or 0)))
        updates.append(f"{key}=?")
        params.append(value)
    if not updates:
        return get_execution_task(task_id)
    updates.append("updated_at=?")
    params.append(int(time.time()))
    params.append(task_id)
    with cursor() as cur:
        cur.execute(f"UPDATE execution_tasks SET {', '.join(updates)} WHERE id=?", params)
    return get_execution_task(task_id)


def add_task_event(task_id, event_type, content=""):
    with cursor() as cur:
        cur.execute(
            "INSERT INTO task_events(task_id,event_type,content,created_at) VALUES(?,?,?,?)",
            (task_id, event_type, str(content)[:4000], int(time.time())),
        )


def _task_dict(row, include_events=False):
    task = dict(row)
    try:
        task["metadata"] = json.loads(task.get("metadata") or "{}")
    except (TypeError, ValueError):
        task["metadata"] = {}
    if include_events:
        with cursor() as cur:
            cur.execute(
                "SELECT id,event_type,content,created_at FROM task_events "
                "WHERE task_id=? ORDER BY id",
                (task["id"],),
            )
            task["events"] = [dict(event) for event in cur.fetchall()]
    return task


def get_execution_task(task_id, user_id=None, include_events=True):
    clauses = ["id=?"]
    params = [task_id]
    if user_id is not None:
        clauses.append("user_id=?")
        params.append(user_id)
    with cursor() as cur:
        cur.execute(f"SELECT * FROM execution_tasks WHERE {' AND '.join(clauses)}", params)
        row = cur.fetchone()
    return _task_dict(row, include_events=include_events) if row else None


def list_execution_tasks(user_id, experiment_id=None, limit=20):
    clauses = ["user_id=?"]
    params = [user_id]
    if experiment_id is not None:
        clauses.append("experiment_id=?")
        params.append(experiment_id)
    params.append(min(100, max(1, int(limit or 20))))
    with cursor() as cur:
        cur.execute(
            f"SELECT * FROM execution_tasks WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            params,
        )
        rows = cur.fetchall()
    return [_task_dict(row, include_events=True) for row in rows]


def find_active_task(user_id, experiment_id, kind):
    with cursor() as cur:
        cur.execute(
            "SELECT * FROM execution_tasks WHERE user_id=? AND experiment_id=? "
            "AND kind=? AND status IN ('queued','running') ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (user_id, experiment_id, kind),
        )
        row = cur.fetchone()
    return _task_dict(row, include_events=True) if row else None


def interrupt_incomplete_tasks():
    now = int(time.time())
    message = "服务已重启，任务执行状态已中断，请重新发起"
    with cursor() as cur:
        cur.execute(
            "SELECT id FROM execution_tasks WHERE status IN ('queued','running')"
        )
        task_ids = [row["id"] for row in cur.fetchall()]
        if task_ids:
            marks = ",".join("?" for _ in task_ids)
            cur.execute(
                f"UPDATE execution_tasks SET status='interrupted', detail=?, error=?, "
                f"finished_at=?, updated_at=? WHERE id IN ({marks})",
                (message, message, now, now, *task_ids),
            )
            cur.executemany(
                "INSERT INTO task_events(task_id,event_type,content,created_at) VALUES(?,?,?,?)",
                [(task_id, "interrupted", message, now) for task_id in task_ids],
            )
    return len(task_ids)


# --------------------------------------------------------------------------------------
# 论文工作区：每个工作区对应一个实验，持久保存输入与全流程产物
# --------------------------------------------------------------------------------------

_PAPER_JSON_FIELDS = ("resource_spec", "config_json", "schedule_json", "analysis_json")


def _json_load(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def create_paper_workspace(user_id, experiment_id, name, goal, mode, resource_spec):
    now = int(time.time())
    workspace_id = uuid.uuid4().hex
    with cursor() as cur:
        cur.execute(
            "INSERT INTO paper_workspaces("
            "id,user_id,experiment_id,name,goal,mode,status,stage,resource_spec,created_at,updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                workspace_id, user_id, experiment_id, name, goal, mode,
                "queued", "intake", json.dumps(resource_spec or {}, ensure_ascii=False), now, now,
            ),
        )
    add_paper_workspace_event(workspace_id, "intake", "queued", "工作区已创建，等待处理")
    return get_paper_workspace(workspace_id, user_id=user_id)


def update_paper_workspace(workspace_id, **changes):
    allowed = {
        "name", "goal", "mode", "status", "stage", "resource_spec", "config_json",
        "schedule_json", "analysis_json", "report_md", "retries", "resources_reclaimed",
        "finished_at",
    }
    updates, params = [], []
    for key, value in changes.items():
        if key not in allowed:
            continue
        if key in _PAPER_JSON_FIELDS and not isinstance(value, str):
            value = json.dumps(value or {}, ensure_ascii=False)
        if key == "resources_reclaimed":
            value = 1 if value else 0
        updates.append(f"{key}=?")
        params.append(value)
    if not updates:
        return get_paper_workspace(workspace_id)
    updates.append("updated_at=?")
    params.extend((int(time.time()), workspace_id))
    with cursor() as cur:
        cur.execute(f"UPDATE paper_workspaces SET {', '.join(updates)} WHERE id=?", params)
    return get_paper_workspace(workspace_id)


def add_paper_workspace_file(
    workspace_id, user_id, original_name, stored_path, size, content_type="", artifact_type="input"
):
    now = int(time.time())
    with cursor() as cur:
        cur.execute(
            "INSERT INTO paper_workspace_files("
            "workspace_id,user_id,original_name,stored_path,size,content_type,artifact_type,created_at"
            ") VALUES(?,?,?,?,?,?,?,?)",
            (
                workspace_id, user_id, original_name, stored_path, int(size or 0),
                content_type or "", artifact_type or "input", now,
            ),
        )
        file_id = cur.lastrowid
        cur.execute("SELECT * FROM paper_workspace_files WHERE id=?", (file_id,))
        return dict(cur.fetchone())


def add_paper_workspace_event(workspace_id, phase, event_type, content="", data=None):
    now = int(time.time())
    with cursor() as cur:
        cur.execute(
            "INSERT INTO paper_workspace_events(workspace_id,phase,event_type,content,data,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                workspace_id, phase, event_type, str(content or "")[:4000],
                json.dumps(data or {}, ensure_ascii=False), now,
            ),
        )
        return cur.lastrowid


def _paper_workspace_dict(row, include_details=False):
    item = dict(row)
    for field in _PAPER_JSON_FIELDS:
        item[field] = _json_load(item.get(field), {})
    item["resources_reclaimed"] = bool(item.get("resources_reclaimed"))
    if include_details:
        with cursor() as cur:
            cur.execute(
                "SELECT id,workspace_id,original_name,size,content_type,artifact_type,created_at "
                "FROM paper_workspace_files WHERE workspace_id=? ORDER BY id",
                (item["id"],),
            )
            item["files"] = [dict(row) for row in cur.fetchall()]
            cur.execute(
                "SELECT id,phase,event_type,content,data,created_at "
                "FROM paper_workspace_events WHERE workspace_id=? ORDER BY id",
                (item["id"],),
            )
            events = []
            for event_row in cur.fetchall():
                event = dict(event_row)
                event["data"] = _json_load(event.get("data"), {})
                events.append(event)
            item["events"] = events
    return item


def get_paper_workspace(workspace_id, user_id=None, include_details=True):
    clauses, params = ["w.id=?"], [workspace_id]
    if user_id is not None:
        clauses.append("w.user_id=?")
        params.append(user_id)
    with cursor() as cur:
        cur.execute(
            "SELECT w.*, e.name AS experiment_name FROM paper_workspaces w "
            "LEFT JOIN experiments e ON e.id=w.experiment_id "
            f"WHERE {' AND '.join(clauses)}",
            params,
        )
        row = cur.fetchone()
    return _paper_workspace_dict(row, include_details=include_details) if row else None


def get_paper_workspace_for_experiment(experiment_id, user_id=None, include_details=True):
    clauses, params = ["w.experiment_id=?"], [experiment_id]
    if user_id is not None:
        clauses.append("w.user_id=?")
        params.append(user_id)
    with cursor() as cur:
        cur.execute(
            "SELECT w.*, e.name AS experiment_name FROM paper_workspaces w "
            "LEFT JOIN experiments e ON e.id=w.experiment_id "
            f"WHERE {' AND '.join(clauses)}",
            params,
        )
        row = cur.fetchone()
    return _paper_workspace_dict(row, include_details=include_details) if row else None


def list_paper_workspaces(user_id, limit=50, include_all=False):
    with cursor() as cur:
        limit = min(100, max(1, int(limit or 50)))
        if include_all:
            cur.execute(
                "SELECT w.*, e.name AS experiment_name, u.username AS owner_username, "
                "'admin' AS access_role FROM paper_workspaces w "
                "LEFT JOIN experiments e ON e.id=w.experiment_id "
                "LEFT JOIN users u ON u.id=w.user_id "
                "ORDER BY w.created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cur.execute(
                "SELECT w.*, e.name AS experiment_name, u.username AS owner_username, "
                "CASE WHEN w.user_id=? THEN 'owner' ELSE 'collaborator' END AS access_role "
                "FROM paper_workspaces w LEFT JOIN experiments e ON e.id=w.experiment_id "
                "LEFT JOIN users u ON u.id=w.user_id "
                "LEFT JOIN experiment_collaborators c "
                "ON c.experiment_id=w.experiment_id AND c.user_id=? "
                "WHERE w.user_id=? OR c.user_id=? ORDER BY w.created_at DESC LIMIT ?",
                (user_id, user_id, user_id, user_id, limit),
            )
        rows = cur.fetchall()
    return [_paper_workspace_dict(row, include_details=False) for row in rows]


def get_paper_workspace_file(file_id, user_id=None):
    clauses, params = ["id=?"], [file_id]
    if user_id is not None:
        clauses.append("user_id=?")
        params.append(user_id)
    with cursor() as cur:
        cur.execute(f"SELECT * FROM paper_workspace_files WHERE {' AND '.join(clauses)}", params)
        row = cur.fetchone()
    return dict(row) if row else None


def list_paper_workspace_files_internal(workspace_id, user_id=None):
    clauses, params = ["workspace_id=?"], [workspace_id]
    if user_id is not None:
        clauses.append("user_id=?")
        params.append(user_id)
    with cursor() as cur:
        cur.execute(
            f"SELECT * FROM paper_workspace_files WHERE {' AND '.join(clauses)} ORDER BY id",
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def interrupt_incomplete_paper_workspaces():
    now = int(time.time())
    message = "服务已重启，工作流已中断；已创建的资源会保留，可在工作区中检查"
    with cursor() as cur:
        cur.execute("SELECT id FROM paper_workspaces WHERE status IN ('queued','running')")
        workspace_ids = [row["id"] for row in cur.fetchall()]
        if workspace_ids:
            marks = ",".join("?" for _ in workspace_ids)
            cur.execute(
                f"UPDATE paper_workspaces SET status='interrupted', updated_at=?, finished_at=? "
                f"WHERE id IN ({marks})",
                (now, now, *workspace_ids),
            )
            cur.executemany(
                "INSERT INTO paper_workspace_events(workspace_id,phase,event_type,content,data,created_at) "
                "VALUES(?,?,?,?,?,?)",
                [(workspace_id, "system", "interrupted", message, "{}", now) for workspace_id in workspace_ids],
            )
    return len(workspace_ids)


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


def update_experiment(exp_id: int, name: str, description: str = "") -> dict | None:
    name = (name or "").strip() or "未命名实验"
    with cursor() as cur:
        cur.execute(
            "UPDATE experiments SET name=?, description=? WHERE id=?",
            (name, description or "", exp_id),
        )
        cur.execute("SELECT * FROM experiments WHERE id=?", (exp_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def get_experiment(exp_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT e.*, u.username AS owner_username FROM experiments e "
            "LEFT JOIN users u ON u.id = e.user_id WHERE e.id=?",
            (exp_id,),
        )
        r = cur.fetchone()
    return dict(r) if r else None


def experiment_access_role(exp_id: int, user_id: int, is_admin: bool = False) -> str | None:
    if is_admin:
        return "admin" if get_experiment(exp_id) else None
    with cursor() as cur:
        cur.execute(
            "SELECT CASE WHEN e.user_id=? THEN 'owner' "
            "WHEN c.user_id IS NOT NULL THEN 'collaborator' END AS access_role "
            "FROM experiments e LEFT JOIN experiment_collaborators c "
            "ON c.experiment_id=e.id AND c.user_id=? WHERE e.id=?",
            (user_id, user_id, exp_id),
        )
        row = cur.fetchone()
    return row["access_role"] if row and row["access_role"] else None


def list_experiments(user_id: int | None = None) -> list[dict]:
    """user_id=None 返回所有；否则返回用户拥有或参与的实验。"""
    with cursor() as cur:
        if user_id is None:
            cur.execute(
                "SELECT e.*, u.username AS owner_username, 'admin' AS access_role "
                "FROM experiments e "
                "LEFT JOIN users u ON u.id = e.user_id ORDER BY e.id DESC"
            )
        else:
            cur.execute(
                "SELECT e.*, u.username AS owner_username, "
                "CASE WHEN e.user_id=? THEN 'owner' ELSE 'collaborator' END AS access_role "
                "FROM experiments e LEFT JOIN users u ON u.id=e.user_id "
                "LEFT JOIN experiment_collaborators c "
                "ON c.experiment_id=e.id AND c.user_id=? "
                "WHERE e.user_id=? OR c.user_id=? ORDER BY e.id DESC",
                (user_id, user_id, user_id, user_id),
            )
        return [dict(r) for r in cur.fetchall()]


def list_experiment_collaborators(exp_id: int) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            "SELECT u.id AS user_id, u.username, u.name, u.avatar_url, "
            "c.added_by, c.created_at FROM experiment_collaborators c "
            "JOIN users u ON u.id=c.user_id WHERE c.experiment_id=? "
            "ORDER BY c.created_at, u.id",
            (exp_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def list_experiment_collaborator_user_ids(exp_id: int) -> list[int]:
    with cursor() as cur:
        cur.execute(
            "SELECT user_id FROM experiment_collaborators WHERE experiment_id=?",
            (exp_id,),
        )
        return [int(row["user_id"]) for row in cur.fetchall()]


def find_user_by_username(username: str) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT id,username,name,avatar_url,role,created_at FROM users "
            "WHERE username=?",
            ((username or "").strip(),),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def add_experiment_collaborator(exp_id: int, user_id: int, added_by: int) -> bool:
    with cursor() as cur:
        cur.execute(
            "INSERT OR IGNORE INTO experiment_collaborators("
            "experiment_id,user_id,added_by,created_at) VALUES(?,?,?,?)",
            (exp_id, user_id, added_by, int(time.time())),
        )
        return cur.rowcount > 0


def remove_experiment_collaborator(exp_id: int, user_id: int) -> bool:
    with cursor() as cur:
        cur.execute(
            "DELETE FROM experiment_collaborators WHERE experiment_id=? AND user_id=?",
            (exp_id, user_id),
        )
        return cur.rowcount > 0


def get_experiment_share(exp_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute("SELECT * FROM experiment_shares WHERE experiment_id=?", (exp_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def ensure_experiment_share(exp_id: int, created_by: int) -> dict:
    existing = get_experiment_share(exp_id)
    if existing:
        return existing
    for _ in range(3):
        token = secrets.token_urlsafe(24)
        try:
            with cursor() as cur:
                cur.execute(
                    "INSERT INTO experiment_shares(experiment_id,token,created_by,created_at) "
                    "VALUES(?,?,?,?)",
                    (exp_id, token, created_by, int(time.time())),
                )
            return get_experiment_share(exp_id)
        except sqlite3.IntegrityError:
            existing = get_experiment_share(exp_id)
            if existing:
                return existing
    raise RuntimeError("无法生成唯一分享链接")


def revoke_experiment_share(exp_id: int) -> bool:
    with cursor() as cur:
        cur.execute("DELETE FROM experiment_shares WHERE experiment_id=?", (exp_id,))
        return cur.rowcount > 0


def get_experiment_by_share_token(token: str) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT e.*, u.username AS owner_username, s.created_at AS shared_at "
            "FROM experiment_shares s JOIN experiments e ON e.id=s.experiment_id "
            "LEFT JOIN users u ON u.id=e.user_id WHERE s.token=?",
            ((token or "").strip(),),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def delete_experiment(exp_id: int):
    """删除实验及其任务、工作区、上传文件元数据，返回待移除的磁盘路径。"""
    with cursor() as cur:
        cur.execute(
            "SELECT f.stored_path FROM paper_workspace_files f "
            "JOIN paper_workspaces w ON w.id=f.workspace_id WHERE w.experiment_id=?",
            (exp_id,),
        )
        stored_paths = [row["stored_path"] for row in cur.fetchall()]
        cur.execute("SELECT stored_path FROM script_files WHERE experiment_id=?", (exp_id,))
        stored_paths.extend(row["stored_path"] for row in cur.fetchall())
        cur.execute("SELECT id FROM execution_tasks WHERE experiment_id=?", (exp_id,))
        task_ids = [row["id"] for row in cur.fetchall()]
        if task_ids:
            marks = ",".join("?" for _ in task_ids)
            cur.execute(f"DELETE FROM task_events WHERE task_id IN ({marks})", task_ids)
        cur.execute("DELETE FROM execution_tasks WHERE experiment_id=?", (exp_id,))
        cur.execute("SELECT id FROM paper_workspaces WHERE experiment_id=?", (exp_id,))
        workspace_ids = [row["id"] for row in cur.fetchall()]
        if workspace_ids:
            marks = ",".join("?" for _ in workspace_ids)
            cur.execute(f"DELETE FROM paper_workspace_events WHERE workspace_id IN ({marks})", workspace_ids)
            cur.execute(f"DELETE FROM paper_workspace_files WHERE workspace_id IN ({marks})", workspace_ids)
            cur.execute(f"DELETE FROM paper_workspaces WHERE id IN ({marks})", workspace_ids)
        cur.execute("DELETE FROM experiment_collaborators WHERE experiment_id=?", (exp_id,))
        cur.execute("DELETE FROM experiment_shares WHERE experiment_id=?", (exp_id,))
        cur.execute("DELETE FROM chat_history WHERE experiment_id=?", (exp_id,))
        cur.execute("DELETE FROM script_files WHERE experiment_id=?", (exp_id,))
        cur.execute("DELETE FROM experiments WHERE id=?", (exp_id,))
    return stored_paths


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
