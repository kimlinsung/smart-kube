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
from .config import ADMIN_CONF


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
        cur.execute("SELECT id, username, role FROM users WHERE id=?", (uid,))
        row = cur.fetchone()
    return dict(row) if row else None


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
