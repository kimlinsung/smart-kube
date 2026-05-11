"""HTTP REST API 路由。"""
from __future__ import annotations

import os
import time
import uuid

import json

from flask import Blueprint, Response, jsonify, request, session, stream_with_context
from werkzeug.utils import secure_filename

from . import agent, auth, db, k8s_client
from .config import UPLOAD_DIR

bp = Blueprint("api", __name__, url_prefix="/api")


# --------------------------------------------------------------------------------------
# 公开接口（无需登录；仅返回静态展示数据，不接触集群）
# --------------------------------------------------------------------------------------

# 云边端多智能体实验床设备清单（恒定数据，专用于公开展示页面）
# - category: cloud / edge / iot  （云 / 边 / 端）
# - has_online_status:
#     True  -> 展示在线/离线状态（所有数量均视为在线）
#     False -> 仅展示数量，不参与在线状态
_PUBLIC_DEVICE_INVENTORY = [
    # ---- Cloud ----
    {"category": "cloud", "device": "Dell PowerEdge R750",       "isa": "x86_64",   "discrete_gpu": True,  "count": 7,  "has_online_status": True},
    {"category": "cloud", "device": "Cisco Rack Server",         "isa": "x86_64",   "discrete_gpu": True,  "count": 1,  "has_online_status": True},
    {"category": "cloud", "device": "Dell Precision 3680",       "isa": "x86_64",   "discrete_gpu": False, "count": 1,  "has_online_status": True},

    # ---- Edge ----
    {"category": "edge",  "device": "NVIDIA Jetson Orin NX",     "isa": "ARM64",    "discrete_gpu": True,  "count": 12, "has_online_status": True},
    {"category": "edge",  "device": "NVIDIA Jetson AGX Orin",    "isa": "ARM64",    "discrete_gpu": True,  "count": 2,  "has_online_status": True},
    {"category": "edge",  "device": "Milk-V Meles",              "isa": "RISC-V 64","discrete_gpu": False, "count": 8,  "has_online_status": True},
    {"category": "edge",  "device": "Milk-V Pioneer",            "isa": "RISC-V 64","discrete_gpu": True,  "count": 2,  "has_online_status": True},
    {"category": "edge",  "device": "StarFive VisionFive 2",     "isa": "RISC-V 64","discrete_gpu": False, "count": 6,  "has_online_status": True},
    {"category": "edge",  "device": "NVIDIA Jetson Nano",        "isa": "ARM64",    "discrete_gpu": True,  "count": 16, "has_online_status": True},
    {"category": "edge",  "device": "Raspberry Pi 5 (8GB)",      "isa": "ARM64",    "discrete_gpu": False, "count": 16, "has_online_status": True},

    # ---- IoT (端) ----
    # 仅 Yahboom ROS car 与 PuppyPi 参与在线状态展示，其余仅展示数量
    {"category": "iot",   "device": "Yahboom ROS Car",           "isa": "ARM64",    "discrete_gpu": False, "count": 4,  "has_online_status": True},
    {"category": "iot",   "device": "PuppyPi",                   "isa": "ARM64",    "discrete_gpu": False, "count": 4,  "has_online_status": True},
    {"category": "iot",   "device": "Intel RealSense D435i",     "isa": "—",        "discrete_gpu": False, "count": 10, "has_online_status": False},
    {"category": "iot",   "device": "STM32",                     "isa": "ARM32",    "discrete_gpu": False, "count": 30, "has_online_status": False},
    {"category": "iot",   "device": "Songle 3 Relay",            "isa": "—",        "discrete_gpu": False, "count": 20, "has_online_status": False},
    {"category": "iot",   "device": "ATmega328P",                "isa": "AVR 8-bit","discrete_gpu": False, "count": 10, "has_online_status": False},
    {"category": "iot",   "device": "Orange Pi Zero 2",          "isa": "ARM64",    "discrete_gpu": False, "count": 10, "has_online_status": False},
    {"category": "iot",   "device": "Mi Home Kits",              "isa": "—",        "discrete_gpu": False, "count": 22, "has_online_status": False},
    {"category": "iot",   "device": "TelosB",                    "isa": "MSP430",   "discrete_gpu": False, "count": 20, "has_online_status": False},
]


@bp.get("/public/devices")
def public_devices():
    """对外展示：返回云边端实验床设备清单。

    该接口**完全不访问 Kubernetes 集群**，仅返回恒定的静态数据，
    安全地暴露在公网。所有"在线数量"等于"数量"，状态恒为在线。
    """
    devices = []
    totals = {"cloud": 0, "edge": 0, "iot": 0, "all": 0, "online": 0}
    for d in _PUBLIC_DEVICE_INVENTORY:
        count = int(d["count"])
        online = count if d["has_online_status"] else None
        status = "online" if d["has_online_status"] else "n/a"
        devices.append({
            "category":          d["category"],
            "device":            d["device"],
            "isa":               d["isa"],
            "discrete_gpu":      bool(d["discrete_gpu"]),
            "count":             count,
            "online_count":      online,
            "has_online_status": d["has_online_status"],
            "status":            status,
        })
        totals[d["category"]] = totals.get(d["category"], 0) + count
        totals["all"] += count
        if d["has_online_status"]:
            totals["online"] += count
    return jsonify({"devices": devices, "totals": totals})


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
    session["current_experiment_id"] = db.ensure_default_experiment(user["id"])
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
    exp_id = _current_experiment_id(u)
    exp = db.get_experiment(exp_id) if exp_id else None
    return jsonify({
        **u,
        "current_experiment_id": exp_id,
        "current_experiment_name": exp["name"] if exp else None,
    })


def _current_experiment_id(user: dict) -> int:
    """读取 session 中的当前实验 id；缺失/失效时回退到该用户的默认实验，并写回 session。"""
    exp_id = session.get("current_experiment_id")
    if exp_id:
        exp = db.get_experiment(exp_id)
        # 普通用户不能"占用"别人的实验做当前活动实验
        if exp and (user["role"] == "admin" or exp["user_id"] == user["id"]):
            return exp_id
    exp_id = db.ensure_default_experiment(user["id"])
    session["current_experiment_id"] = exp_id
    return exp_id


def _summarize_experiment(exp: dict) -> dict:
    """加上 cloud/edge/device pod 数量等汇总字段。"""
    pods = k8s_client.list_pods_by_experiment(exp["id"])
    counts = {"cloud": 0, "edge": 0, "device": 0}
    for p in pods:
        nt = p.get("node_type") or "edge"
        counts[nt] = counts.get(nt, 0) + 1
    return {
        "id": exp["id"],
        "user_id": exp["user_id"],
        "owner_username": exp.get("owner_username"),
        "name": exp["name"],
        "description": exp.get("description") or "",
        "created_at": exp["created_at"],
        "cloud_count": counts.get("cloud", 0),
        "edge_count": counts.get("edge", 0),
        "device_count": counts.get("device", 0),
        "total_count": len(pods),
    }


@bp.post("/register")
def register():
    """自助注册已关闭，账号统一由管理员通过 /api/admin/users 创建。"""
    return jsonify({"error": "自助注册已关闭，请联系管理员开通账号"}), 403


# --------------------------------------------------------------------------------------
# 资源
# --------------------------------------------------------------------------------------

@bp.get("/resources")
@auth.login_required
def list_resources():
    u = request.current_user
    pods = k8s_client.list_user_pods(u, all_users=False)
    return jsonify({"pods": pods})


@bp.get("/resources/<pod_name>/describe")
@auth.login_required
def describe_resource(pod_name):
    u = request.current_user
    try:
        k8s_client.assert_pod_owned(pod_name, u)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 404
    info = k8s_client.describe_pod(pod_name)
    if info.get("error"):
        return jsonify(info), 404
    return jsonify(info)


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
    exp_id = _current_experiment_id(u)
    reply = agent.chat(u, text, uploaded_file=uploaded, experiment_id=exp_id)
    return jsonify({"reply": reply})


@bp.post("/chat/stream")
@auth.login_required
def chat_stream():
    u = request.current_user
    data = request.get_json(force=True) or {}
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify({"error": "消息为空"}), 400
    uploaded = session.get("uploaded_file")
    exp_id = _current_experiment_id(u)

    def generate():
        try:
            for token in agent.chat_stream(u, text, uploaded_file=uploaded, experiment_id=exp_id):
                yield f"data: {json.dumps({'delta': token}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.get("/chat/history")
@auth.login_required
def chat_history():
    u = request.current_user
    exp_id = _current_experiment_id(u)
    return jsonify({"history": db.get_chat(u["id"], limit=100, experiment_id=exp_id)})


@bp.delete("/chat/history")
@auth.login_required
def clear_history():
    u = request.current_user
    exp_id = _current_experiment_id(u)
    db.clear_chat(u["id"], experiment_id=exp_id)
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
# 实验（一个实验 = 一个 session，按对话区分云边端 Pod 组合）
# --------------------------------------------------------------------------------------

@bp.get("/experiments")
@auth.login_required
def list_experiments():
    u = request.current_user
    exps = db.list_experiments(user_id=None if u["role"] == "admin" else u["id"])
    items = [_summarize_experiment(e) for e in exps]
    return jsonify({
        "experiments": items,
        "current_experiment_id": _current_experiment_id(u),
    })


@bp.post("/experiments")
@auth.login_required
def create_experiment():
    u = request.current_user
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip() or f"实验-{int(time.time())}"
    desc = (data.get("description") or "").strip()
    exp = db.create_experiment(u["id"], name, desc)
    session["current_experiment_id"] = exp["id"]
    db.log_audit(u["id"], u["username"], "create_experiment", f"{exp['id']}:{name}")
    exp["owner_username"] = u["username"]
    return jsonify(_summarize_experiment(exp))


@bp.get("/experiments/<int:exp_id>")
@auth.login_required
def get_experiment_detail(exp_id):
    u = request.current_user
    exp = db.get_experiment(exp_id)
    if not exp:
        return jsonify({"error": "实验不存在"}), 404
    if u["role"] != "admin" and exp["user_id"] != u["id"]:
        return jsonify({"error": "无权查看他人实验"}), 403
    pods = k8s_client.list_pods_by_experiment(exp_id)
    counts = {"cloud": 0, "edge": 0, "device": 0}
    for p in pods:
        nt = p.get("node_type") or "edge"
        counts[nt] = counts.get(nt, 0) + 1
    return jsonify({
        "experiment": {
            "id": exp["id"],
            "user_id": exp["user_id"],
            "owner_username": exp.get("owner_username"),
            "name": exp["name"],
            "description": exp.get("description") or "",
            "created_at": exp["created_at"],
            "cloud_count": counts.get("cloud", 0),
            "edge_count": counts.get("edge", 0),
            "device_count": counts.get("device", 0),
            "total_count": len(pods),
        },
        "pods": pods,
        "is_current": _current_experiment_id(u) == exp_id,
    })


@bp.post("/experiments/<int:exp_id>/enter")
@auth.login_required
def enter_experiment(exp_id):
    u = request.current_user
    exp = db.get_experiment(exp_id)
    if not exp:
        return jsonify({"error": "实验不存在"}), 404
    if u["role"] != "admin" and exp["user_id"] != u["id"]:
        return jsonify({"error": "无权进入他人实验"}), 403
    session["current_experiment_id"] = exp_id
    db.log_audit(u["id"], u["username"], "enter_experiment", str(exp_id))
    return jsonify({"ok": True, "current_experiment_id": exp_id, "name": exp["name"]})


@bp.delete("/experiments/<int:exp_id>")
@auth.login_required
def delete_experiment(exp_id):
    u = request.current_user
    exp = db.get_experiment(exp_id)
    if not exp:
        return jsonify({"error": "实验不存在"}), 404
    if u["role"] != "admin" and exp["user_id"] != u["id"]:
        return jsonify({"error": "无权删除他人实验"}), 403
    try:
        deleted_pods = k8s_client.delete_pods_by_experiment(exp_id)
    except Exception as e:
        return jsonify({"error": f"清理 Pod 失败：{e}"}), 500
    db.delete_experiment(exp_id)
    # 当前实验若被删，回退到该用户的默认实验（必要时新建）
    if session.get("current_experiment_id") == exp_id:
        session["current_experiment_id"] = db.ensure_default_experiment(u["id"])
    db.log_audit(u["id"], u["username"], "delete_experiment", f"{exp_id}:pods={len(deleted_pods)}")
    return jsonify({"ok": True, "deleted_pods": deleted_pods})


# --------------------------------------------------------------------------------------
# 管理员接口
# --------------------------------------------------------------------------------------

@bp.get("/admin/nodes")
@auth.admin_required
def admin_nodes():
    return jsonify({"nodes": k8s_client.list_nodes()})


@bp.post("/admin/nodes/<node_name>/cordon")
@auth.admin_required
def admin_cordon_node(node_name):
    u = request.current_user
    try:
        k8s_client.cordon_node(node_name)
        db.log_audit(u["id"], u["username"], "cordon_node", node_name)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.post("/admin/nodes/<node_name>/uncordon")
@auth.admin_required
def admin_uncordon_node(node_name):
    u = request.current_user
    try:
        k8s_client.uncordon_node(node_name)
        db.log_audit(u["id"], u["username"], "uncordon_node", node_name)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


@bp.put("/admin/users/<int:uid>/password")
@auth.admin_required
def admin_change_password(uid):
    u = request.current_user
    data = request.get_json(force=True) or {}
    new_pwd = data.get("password", "").strip()
    err = auth.change_password(uid, new_pwd)
    if err:
        return jsonify({"error": err}), 400
    db.log_audit(u["id"], u["username"], "change_password", f"uid={uid}")
    return jsonify({"ok": True})


@bp.put("/admin/users/<int:uid>/role")
@auth.admin_required
def admin_set_role(uid):
    u = request.current_user
    if uid == u["id"]:
        return jsonify({"error": "不能修改自己的角色"}), 400
    data = request.get_json(force=True) or {}
    role = (data.get("role") or "").strip()
    err = auth.set_role(uid, role)
    if err:
        return jsonify({"error": err}), 400
    db.log_audit(u["id"], u["username"], "set_role", f"uid={uid} role={role}")
    return jsonify({"ok": True})


@bp.delete("/admin/users/<int:uid>")
@auth.admin_required
def admin_delete_user(uid):
    u = request.current_user
    auth.delete_user(uid)
    db.log_audit(u["id"], u["username"], "delete_user", str(uid))
    return jsonify({"ok": True})
