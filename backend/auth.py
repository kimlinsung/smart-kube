"""认证与权限：用户 CRUD、密码 hash、登录、session 鉴权装饰器。"""
import time
from functools import wraps
from typing import Optional

from flask import session, jsonify, request
from werkzeug.security import generate_password_hash as _gph, check_password_hash


# Werkzeug 3 默认用 scrypt，但 macOS 系统自带的 LibreSSL 不支持 scrypt。
# 这里强制使用 pbkdf2:sha256，跨平台都可用。
def generate_password_hash(password: str) -> str:
    return _gph(password, method="pbkdf2:sha256")

from . import db
from .config import ADMIN_CONF, FEISHU_CONF


def ensure_admin():
    """启动时确保默认管理员存在。"""
    username = ADMIN_CONF.get("username", "admin")
    password = ADMIN_CONF.get("password", "admin123")
    with db.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username=?", (username,))
        if cur.fetchone():
            return
        cur.execute(
            "INSERT INTO users(username, password_hash, role, created_at) VALUES(?,?,?,?)",
            (username, generate_password_hash(password), "admin", int(time.time())),
        )


def create_user(username, password, role="user"):
    if not username or not password:
        return None, "用户名/密码不能为空"
    with db.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username=?", (username,))
        if cur.fetchone():
            return None, "用户名已存在"
        cur.execute(
            "INSERT INTO users(username, password_hash, role, created_at) VALUES(?,?,?,?)",
            (username, generate_password_hash(password), role, int(time.time())),
        )
        cur.execute("SELECT * FROM users WHERE username=?", (username,))
        return dict(cur.fetchone()), None


def list_users():
    with db.cursor() as cur:
        cur.execute("SELECT id, username, role, created_at FROM users ORDER BY id")
        return [dict(r) for r in cur.fetchall()]


def change_password(user_id: int, new_password: str) -> Optional[str]:
    """更新指定用户的密码，返回错误字符串或 None（成功）。"""
    if not new_password or len(new_password) < 6:
        return "密码长度不能少于 6 位"
    with db.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE id=?", (user_id,))
        if not cur.fetchone():
            return "用户不存在"
        cur.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (generate_password_hash(new_password), user_id),
        )
    return None


def delete_user(user_id):
    with db.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id=? AND role!='admin'", (user_id,))


def set_role(user_id: int, role: str) -> Optional[str]:
    """更新指定用户的角色（user / admin）。返回错误字符串或 None（成功）。

    最后一个管理员不允许被降级，避免把自己锁在外面。
    """
    if role not in ("user", "admin"):
        return "角色必须是 user 或 admin"
    with db.cursor() as cur:
        cur.execute("SELECT role FROM users WHERE id=?", (user_id,))
        row = cur.fetchone()
        if not row:
            return "用户不存在"
        current = row["role"]
        if current == role:
            return None
        if current == "admin" and role == "user":
            cur.execute("SELECT COUNT(*) AS c FROM users WHERE role='admin'")
            if cur.fetchone()["c"] <= 1:
                return "至少需要保留一个管理员"
        cur.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    return None


def authenticate(username, password):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE username=?", (username,))
        row = cur.fetchone()
    if not row:
        return None
    user = dict(row)
    if check_password_hash(user["password_hash"], password):
        return user
    return None


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, username, role, name, email, avatar_url, feishu_open_id "
            "FROM users WHERE id=?",
            (uid,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def upsert_feishu_user(info: dict) -> dict:
    """飞书登录回调成功后调用：根据 open_id 找本地用户，没有则自动创建。

    info 来自 feishu.fetch_user_info()，关键字段：
      - open_id / union_id：稳定唯一标识
      - name：中文名；en_name：英文名
      - email / enterprise_email / mobile
      - avatar_url
    """
    open_id  = (info.get("open_id")  or "").strip()
    union_id = (info.get("union_id") or "").strip()
    name     = (info.get("name") or info.get("en_name") or "").strip()
    email    = (info.get("email") or info.get("enterprise_email") or "").strip()
    avatar   = (info.get("avatar_url") or "").strip()
    if not open_id:
        raise ValueError("飞书返回的用户信息里缺少 open_id")

    default_role = FEISHU_CONF.get("default_role", "user")
    if default_role not in ("user", "admin"):
        default_role = "user"

    with db.cursor() as cur:
        # 先按 open_id 查
        cur.execute("SELECT * FROM users WHERE feishu_open_id=?", (open_id,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE users SET feishu_union_id=?, name=?, email=?, avatar_url=? WHERE id=?",
                (union_id, name, email, avatar, row["id"]),
            )
            cur.execute("SELECT * FROM users WHERE id=?", (row["id"],))
            return dict(cur.fetchone())

        # 没有则创建。username 必须唯一，用「飞书姓名 + open_id 末 6 位」拼，冲突再加序号
        base = (name or "feishu_user").replace(" ", "_") + "_" + open_id[-6:]
        username = base
        i = 1
        while True:
            cur.execute("SELECT 1 FROM users WHERE username=?", (username,))
            if not cur.fetchone():
                break
            i += 1
            username = f"{base}_{i}"

        # 飞书登录用户没有本地密码，写一个不可登录的占位 hash
        placeholder_pwd = generate_password_hash("!feishu-no-password!" + open_id)
        cur.execute(
            "INSERT INTO users(username, password_hash, role, created_at, "
            "feishu_open_id, feishu_union_id, name, email, avatar_url) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (username, placeholder_pwd, default_role, int(time.time()),
             open_id, union_id, name, email, avatar),
        )
        cur.execute("SELECT * FROM users WHERE feishu_open_id=?", (open_id,))
        return dict(cur.fetchone())


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u:
            return jsonify({"error": "未登录"}), 401
        request.current_user = u
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u:
            return jsonify({"error": "未登录"}), 401
        if u["role"] != "admin":
            return jsonify({"error": "需要管理员权限"}), 403
        request.current_user = u
        return view(*args, **kwargs)

    return wrapper
