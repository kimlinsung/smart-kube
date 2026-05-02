"""HTTP REST API 路由。"""
from __future__ import annotations

import os
import time
import uuid

from flask import Blueprint, jsonify, request, session
from werkzeug.utils import secure_filename

from . import agent, auth, db, k8s_client
from .config import UPLOAD_DIR

bp = Blueprint("api", __name__, url_prefix="/api")


# --------------------------------------------------------------------------------------
# 认证
# --------------------------------------------------------------------------------------

@bp.post("/login")
def login():
    data = request.get_json(force=True) or {}
    user = auth.authenticate(data.get("username", ""), data.get("password", ""))
    if not user:
        return jsonify({"error": "用户名或密码错误"}), 401
    session.clear()
    session["user_id"] = user["id"]
    db.log_audit(user["id"], user["username"], "login", "")
    return jsonify({"id": user["id"], "username": user["username"], "role": user["role"]})


@bp.post("/logout")
def logout():
    u = auth.current_user()
    if u:
        db.log_audit(u["id"], u["username"], "logout", "")
    session.clear()
    return jsonify({"ok": True})


@bp.get("/me")
def me():
    u = auth.current_user()
    if not u:
        return jsonify({"error": "未登录"}), 401
    return jsonify(u)


@bp.post("/register")
def register():
    """开放普通用户注册（如不希望开放可在前端隐藏入口；管理员注册需要现有管理员调用 /admin/users）。"""
    data = request.get_json(force=True) or {}
    user, err = auth.create_user(data.get("username", "").strip(), data.get("password", ""), role="user")
    if err:
        return jsonify({"error": err}), 400
    db.log_audit(user["id"], user["username"], "register", "")
    return jsonify({"id": user["id"], "username": user["username"], "role": user["role"]})


# --------------------------------------------------------------------------------------
# 资源
# --------------------------------------------------------------------------------------

@bp.get("/resources")
@auth.login_required
def list_resources():
    u = request.current_user
    pods = k8s_client.list_user_pods(u, all_users=False)
    return jsonify({"pods": pods})


@bp.delete("/resources/<pod_name>")
@auth.login_required
def delete_resource(pod_name):
    u = request.current_user
    try:
        k8s_client.delete_pod(pod_name, u)
        db.log_audit(u["id"], u["username"], "delete_pod", pod_name)
        return jsonify({"ok": True})
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.get("/cluster/info")
@auth.login_required
def cluster_info():
    return jsonify(k8s_client.cluster_info())


# --------------------------------------------------------------------------------------
# 对话
# --------------------------------------------------------------------------------------

@bp.post("/chat")
@auth.login_required
def chat():
    u = request.current_user
    data = request.get_json(force=True) or {}
    text = (data.get("message") or "").strip()
    uploaded = session.get("uploaded_file")  # 最近一次上传的 .py 路径
    if not text:
        return jsonify({"error": "消息为空"}), 400
    reply = agent.chat(u, text, uploaded_file=uploaded)
    return jsonify({"reply": reply})


@bp.get("/chat/history")
@auth.login_required
def chat_history():
    u = request.current_user
    return jsonify({"history": db.get_chat(u["id"], limit=100)})


@bp.delete("/chat/history")
@auth.login_required
def clear_history():
    u = request.current_user
    db.clear_chat(u["id"])
    return jsonify({"ok": True})


# --------------------------------------------------------------------------------------
# 文件上传
# --------------------------------------------------------------------------------------

@bp.post("/upload")
@auth.login_required
def upload():
    u = request.current_user
    if "file" not in request.files:
        return jsonify({"error": "未提供文件"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "文件名为空"}), 400
    fname = secure_filename(f.filename)
    user_dir = os.path.join(UPLOAD_DIR, str(u["id"]))
    os.makedirs(user_dir, exist_ok=True)
    save_name = f"{int(time.time())}-{uuid.uuid4().hex[:8]}-{fname}"
    save_path = os.path.join(user_dir, save_name)
    f.save(save_path)
    session["uploaded_file"] = save_path
    db.log_audit(u["id"], u["username"], "upload", fname)
    return jsonify({"ok": True, "filename": fname, "path": save_path})


@bp.post("/upload/to_pod")
@auth.login_required
def upload_to_pod():
    """上传文件并直接 cp 进指定 Pod（必须是当前用户所有的 Pod）。"""
    u = request.current_user
    pod_name = request.form.get("pod_name")
    dest_dir = request.form.get("dest_dir") or "/tmp"
    if not pod_name:
        return jsonify({"error": "缺少 pod_name"}), 400
    if "file" not in request.files:
        return jsonify({"error": "未提供文件"}), 400
    try:
        k8s_client.assert_pod_owned(pod_name, u)
    except Exception as e:
        return jsonify({"error": str(e)}), 403
    f = request.files["file"]
    fname = secure_filename(f.filename or "upload.bin")
    user_dir = os.path.join(UPLOAD_DIR, str(u["id"]))
    os.makedirs(user_dir, exist_ok=True)
    tmp_path = os.path.join(user_dir, f"{uuid.uuid4().hex[:8]}-{fname}")
    f.save(tmp_path)
    try:
        pod_path = k8s_client.copy_to_pod(pod_name, tmp_path, dest_dir=dest_dir, filename=fname)
    finally:
        try: os.remove(tmp_path)
        except Exception: pass
    db.log_audit(u["id"], u["username"], "upload_to_pod", f"{pod_name}:{pod_path}")
    return jsonify({"ok": True, "pod_path": pod_path})


# --------------------------------------------------------------------------------------
# 审计日志
# --------------------------------------------------------------------------------------

@bp.get("/logs")
@auth.login_required
def logs():
    u = request.current_user
    if u["role"] == "admin":
        return jsonify({"logs": db.get_audit_logs()})
    return jsonify({"logs": db.get_audit_logs(user_id=u["id"])})


# --------------------------------------------------------------------------------------
# 管理员接口
# --------------------------------------------------------------------------------------

@bp.get("/admin/nodes")
@auth.admin_required
def admin_nodes():
    return jsonify({"nodes": k8s_client.list_nodes()})


@bp.delete("/admin/nodes/<node_name>")
@auth.admin_required
def admin_delete_node(node_name):
    u = request.current_user
    try:
        k8s_client.delete_node(node_name)
        db.log_audit(u["id"], u["username"], "delete_node", node_name)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.get("/admin/pods")
@auth.admin_required
def admin_pods():
    u = request.current_user
    return jsonify({"pods": k8s_client.list_user_pods(u, all_users=True)})


@bp.get("/admin/users")
@auth.admin_required
def admin_users():
    return jsonify({"users": auth.list_users()})


@bp.post("/admin/users")
@auth.admin_required
def admin_create_user():
    u = request.current_user
    data = request.get_json(force=True) or {}
    role = data.get("role", "user")
    if role not in ("user", "admin"):
        role = "user"
    user, err = auth.create_user(data.get("username", "").strip(), data.get("password", ""), role=role)
    if err:
        return jsonify({"error": err}), 400
    db.log_audit(u["id"], u["username"], "create_user", user["username"])
    return jsonify({"id": user["id"], "username": user["username"], "role": user["role"]})


@bp.delete("/admin/users/<int:uid>")
@auth.admin_required
def admin_delete_user(uid):
    u = request.current_user
    auth.delete_user(uid)
    db.log_audit(u["id"], u["username"], "delete_user", str(uid))
    return jsonify({"ok": True})
