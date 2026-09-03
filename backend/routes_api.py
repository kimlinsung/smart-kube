"""HTTP REST API 路由。"""
from __future__ import annotations

import os
import shutil
import time
import uuid

import json

from flask import Blueprint, Response, current_app, jsonify, request, send_file, session, stream_with_context
from werkzeug.utils import secure_filename

from . import agent, audit, auth, db, jobs, k8s_client, paper_jobs, presence, task_events
from .config import UPLOAD_DIR
from .request_meta import client_ip

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
    audit.log(user["id"], user["username"], "login", "")
    return jsonify({"id": user["id"], "username": user["username"], "role": user["role"]})


@bp.post("/logout")
def logout():
    u = auth.current_user()
    if u:
        audit.log(u["id"], u["username"], "logout", "")
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
        "access_role": exp.get("access_role") or "owner",
    }


_SECRET_FIELD_NAMES = {
    "authorization", "cookie", "credential", "credentials", "password", "secret",
    "token", "api_key", "apikey", "access_key", "secret_key", "private_key",
}


def _is_secret_field(key, hide_ssh=False, hide_agent_trace=False):
    normalized = str(key).strip().lower().replace("-", "_")
    if hide_agent_trace and normalized == "agent_trace":
        return True
    if hide_ssh and normalized.startswith("ssh_"):
        return True
    return (
        normalized in _SECRET_FIELD_NAMES
        or normalized.endswith("_password")
        or normalized.endswith("_token")
        or normalized.endswith("_secret")
        or normalized in {"ssh_password", "ssh_command"}
    )


def _sanitize_value(value, *, hide_ssh=False, hide_agent_trace=False):
    if isinstance(value, dict):
        return {
            key: _sanitize_value(
                item, hide_ssh=hide_ssh, hide_agent_trace=hide_agent_trace
            )
            for key, item in value.items()
            if not _is_secret_field(key, hide_ssh, hide_agent_trace)
        }
    if isinstance(value, list):
        return [
            _sanitize_value(item, hide_ssh=hide_ssh, hide_agent_trace=hide_agent_trace)
            for item in value
        ]
    return value


def _sanitize_resource(resource, *, hide_ssh=False):
    return _sanitize_value(resource or {}, hide_ssh=hide_ssh)


def _sanitize_schedule(schedule, *, hide_ssh=False):
    return _sanitize_value(schedule or {}, hide_ssh=hide_ssh)


def _experiment_access(exp, user):
    if not exp or not user:
        return None
    return db.experiment_access_role(
        exp["id"], user["id"], is_admin=user.get("role") == "admin"
    )


def _share_url(token):
    return f"{request.host_url.rstrip('/')}/shared_experiment.html?token={token}"


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
        audit.log(u["id"], u["username"], "delete_pod", pod_name)
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

def _current_uploaded_path(user, experiment_id):
    file_id = session.get("uploaded_file_id")
    script = db.get_script_file_internal(file_id, user_id=user["id"]) if file_id else None
    if not script or script.get("experiment_id") != experiment_id:
        latest = db.get_latest_script_file(user["id"], experiment_id=experiment_id)
        script = db.get_script_file_internal(latest["id"], user_id=user["id"]) if latest else None
    if not script or not os.path.isfile(script["stored_path"]):
        legacy_path = session.get("uploaded_file")
        return legacy_path if legacy_path and os.path.isfile(legacy_path) else None
    session["uploaded_file_id"] = script["id"]
    session["uploaded_file"] = script["stored_path"]
    return script["stored_path"]


@bp.post("/chat/tasks")
@auth.login_required
def start_chat_task():
    u = request.current_user
    data = request.get_json(force=True) or {}
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify({"error": "消息为空"}), 400
    exp_id = _current_experiment_id(u)
    active = db.find_active_task(u["id"], exp_id, "chat")
    if active:
        return jsonify({"error": "已有对话任务正在执行", "task": active}), 409
    task = jobs.start_chat_task(
        current_app._get_current_object(),
        u,
        text,
        _current_uploaded_path(u, exp_id),
        exp_id,
        client_ip(),
    )
    return jsonify({"task": task}), 202


@bp.get("/tasks")
@auth.login_required
def execution_tasks():
    u = request.current_user
    exp_id = _current_experiment_id(u)
    return jsonify({"tasks": db.list_execution_tasks(u["id"], experiment_id=exp_id, limit=30)})

@bp.post("/chat")
@auth.login_required
def chat():
    u = request.current_user
    data = request.get_json(force=True) or {}
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify({"error": "消息为空"}), 400
    exp_id = _current_experiment_id(u)
    uploaded = _current_uploaded_path(u, exp_id)
    reply = agent.chat(
        u,
        text,
        uploaded_file=uploaded,
        experiment_id=exp_id,
        source_ip=client_ip(),
    )
    return jsonify({"reply": reply})


@bp.post("/chat/stream")
@auth.login_required
def chat_stream():
    u = request.current_user
    data = request.get_json(force=True) or {}
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify({"error": "消息为空"}), 400
    exp_id = _current_experiment_id(u)
    uploaded = _current_uploaded_path(u, exp_id)
    source_ip = client_ip()

    def generate():
        try:
            for ev in agent.chat_stream(
                u,
                text,
                uploaded_file=uploaded,
                experiment_id=exp_id,
                source_ip=source_ip,
            ):
                # 兼容：若底层仍 yield 纯字符串，则包一层 delta
                if isinstance(ev, str):
                    ev = {"delta": ev}
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
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

@bp.get("/scripts/current")
@auth.login_required
def current_script():
    u = request.current_user
    exp_id = _current_experiment_id(u)
    script = db.get_latest_script_file(u["id"], experiment_id=exp_id)
    if script:
        internal = db.get_script_file_internal(script["id"], user_id=u["id"])
        if not internal or not os.path.isfile(internal["stored_path"]):
            script = None
    return jsonify({"script": script})

@bp.post("/upload")
@auth.login_required
def upload():
    u = request.current_user
    if "file" not in request.files:
        return jsonify({"error": "未提供文件"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "文件名为空"}), 400
    original_name = f.filename.replace("\\", "/").rsplit("/", 1)[-1][:255]
    extension = os.path.splitext(original_name)[1].lower()
    fname = secure_filename(original_name) or f"upload{extension or '.bin'}"
    user_dir = os.path.join(UPLOAD_DIR, str(u["id"]))
    os.makedirs(user_dir, exist_ok=True)
    save_name = f"{int(time.time())}-{uuid.uuid4().hex[:8]}-{fname}"
    save_path = os.path.join(user_dir, save_name)
    f.save(save_path)
    exp_id = _current_experiment_id(u)
    script = db.create_script_file(
        u["id"],
        exp_id,
        original_name,
        save_path,
        os.path.getsize(save_path),
    )
    public_script = dict(script)
    public_script.pop("stored_path", None)
    task = db.create_execution_task(
        u["id"],
        exp_id,
        "upload",
        f"上传 {original_name}",
        "文件已安全保存，尚未执行",
        {"file_id": script["id"], "filename": original_name, "size": script["size"]},
    )
    db.update_execution_task(
        task["id"],
        status="succeeded",
        progress=100,
        detail="上传完成，等待执行指令",
        result="文件已上传，不会自动运行",
        started_at=task["created_at"],
        finished_at=int(time.time()),
    )
    db.add_task_event(task["id"], "succeeded", "上传完成，文件尚未执行")
    task_events.publish_task(task["id"])
    session["uploaded_file_id"] = script["id"]
    session["uploaded_file"] = save_path
    audit.log(u["id"], u["username"], "upload", original_name)
    return jsonify({"ok": True, "filename": original_name, "script": public_script, "task": db.get_execution_task(task["id"])})


@bp.post("/scripts/<int:file_id>/run")
@auth.login_required
def run_script(file_id):
    u = request.current_user
    exp_id = _current_experiment_id(u)
    script = db.get_script_file_internal(file_id, user_id=u["id"])
    if not script or script.get("experiment_id") != exp_id:
        return jsonify({"error": "脚本不存在或不属于当前实验"}), 404
    if not script["original_name"].lower().endswith(".py"):
        return jsonify({"error": "直接运行仅支持 .py 文件"}), 400
    if not os.path.isfile(script["stored_path"]):
        return jsonify({"error": "上传文件已不存在，请重新上传"}), 410

    data = request.get_json(silent=True) or {}
    arch = (data.get("arch") or "").strip().lower() or None
    if arch not in {None, "amd64", "arm64", "riscv64"}:
        return jsonify({"error": "架构必须是 amd64、arm64 或 riscv64"}), 400
    hostname = (data.get("hostname") or "").strip()[:253] or None
    try:
        timeout = min(600, max(10, int(data.get("timeout") or 120)))
    except (TypeError, ValueError):
        return jsonify({"error": "超时时间必须是整数"}), 400

    active = db.find_active_task(u["id"], exp_id, "script")
    if active:
        return jsonify({"error": "已有脚本任务正在执行", "task": active}), 409
    task = jobs.start_script_task(
        current_app._get_current_object(),
        u,
        script,
        exp_id,
        {"arch": arch, "hostname": hostname, "timeout": timeout},
        client_ip(),
    )
    return jsonify({"task": task}), 202


# --------------------------------------------------------------------------------------
# 论文工作区
# --------------------------------------------------------------------------------------

def _paper_workspace_payload(workspace, include_resources=True, access_role="owner"):
    if not workspace:
        return None
    payload = dict(workspace)
    payload["access_role"] = access_role
    if access_role == "collaborator":
        payload = _sanitize_value(payload, hide_agent_trace=True)
        payload["access_role"] = access_role
    tasks = db.list_execution_tasks(
        workspace["user_id"], experiment_id=workspace["experiment_id"], limit=30
    )
    payload["tasks"] = [
        _sanitize_value(task, hide_agent_trace=True)
        for task in tasks
        if task.get("metadata", {}).get("workspace_id") == workspace["id"]
    ]
    if include_resources:
        try:
            resources = k8s_client.list_pods_by_experiment(workspace["experiment_id"])
            payload["resources"] = (
                [_sanitize_resource(item) for item in resources]
                if access_role == "collaborator" else resources
            )
            payload["resources_available"] = True
        except Exception:
            payload["resources"] = []
            payload["resources_available"] = False
    return payload


@bp.get("/paper/workspaces")
@auth.login_required
def paper_workspaces():
    u = request.current_user
    workspaces = db.list_paper_workspaces(
        u["id"], limit=50, include_all=u["role"] == "admin"
    )
    return jsonify({
        "workspaces": [
            _sanitize_value(item, hide_agent_trace=True)
            if item.get("access_role") == "collaborator" else item
            for item in workspaces
        ]
    })


@bp.post("/paper/workspaces")
@auth.login_required
def create_paper_workspace():
    u = request.current_user
    mode = (request.form.get("mode") or "").strip()
    files = [item for item in request.files.getlist("files") if item and item.filename]
    if mode not in {"resources", "full"}:
        return jsonify({"error": "开始前必须选择执行至调度或完整流程"}), 400
    if not files:
        return jsonify({"error": "请至少上传一个输入文件"}), 400
    if len(files) > 8:
        return jsonify({"error": "单次工作区最多上传 8 个文件"}), 400
    timestamp = time.strftime("%m%d-%H%M")
    workspace_name = f"正在理解输入-{timestamp}"
    goal = "正在由文档理解 Agent 阅读文件正文并生成实验目标"
    experiment = db.create_experiment(
        u["id"], workspace_name, "论文工作区：等待文档理解 Agent 生成实验元信息"
    )
    workspace = db.create_paper_workspace(
        u["id"], experiment["id"], workspace_name, goal, mode, {}
    )
    workspace_dir = os.path.join(UPLOAD_DIR, str(u["id"]), "paper", workspace["id"])
    os.makedirs(workspace_dir, exist_ok=True)
    for index, uploaded in enumerate(files):
        original_name = uploaded.filename.replace("\\", "/").rsplit("/", 1)[-1][:255]
        extension = os.path.splitext(original_name)[1].lower()
        safe_name = secure_filename(original_name) or f"input-{index + 1}{extension}"
        stored_path = os.path.join(workspace_dir, f"{index + 1:02d}-{safe_name}")
        uploaded.save(stored_path)
        size = os.path.getsize(stored_path)
        if size > 20 * 1024 * 1024:
            os.remove(stored_path)
            db.update_paper_workspace(workspace["id"], status="failed", stage="intake")
            db.add_paper_workspace_event(
                workspace["id"], "intake", "failed", f"文件 {original_name} 超过 20 MB"
            )
            return jsonify({"error": f"文件 {original_name} 超过 20 MB"}), 413
        db.add_paper_workspace_file(
            workspace["id"], u["id"], original_name, stored_path, size, uploaded.content_type or ""
        )
    db.add_paper_workspace_event(
        workspace["id"], "intake", "succeeded", f"已归档 {len(files)} 个输入文件"
    )
    session["current_experiment_id"] = experiment["id"]
    workspace = db.get_paper_workspace(workspace["id"], user_id=u["id"])
    task = paper_jobs.start_workspace_job(
        current_app._get_current_object(), workspace, u, client_ip()
    )
    audit.log(
        u["id"], u["username"], "paper_workspace_create",
        json.dumps({"workspace_id": workspace["id"], "experiment_id": experiment["id"], "mode": mode}),
    )
    return jsonify({"workspace": _paper_workspace_payload(workspace), "task": task}), 202


@bp.get("/paper/workspaces/<workspace_id>")
@auth.login_required
def paper_workspace_detail(workspace_id):
    u = request.current_user
    workspace = db.get_paper_workspace(workspace_id)
    if not workspace:
        return jsonify({"error": "工作区不存在"}), 404
    exp = db.get_experiment(workspace["experiment_id"])
    access_role = _experiment_access(exp, u)
    if not access_role:
        return jsonify({"error": "无权查看此工作区"}), 403
    return jsonify({
        "workspace": _paper_workspace_payload(workspace, access_role=access_role)
    })


def _authorized_workspace_file(workspace_id, file_id, user):
    workspace = db.get_paper_workspace(workspace_id, include_details=False)
    if not workspace:
        return None, None, None
    exp = db.get_experiment(workspace["experiment_id"])
    access_role = _experiment_access(exp, user)
    item = db.get_paper_workspace_file(file_id)
    if not access_role or not item or item["workspace_id"] != workspace_id:
        return workspace, None, access_role
    return workspace, item, access_role


@bp.get("/paper/workspaces/<workspace_id>/files/<int:file_id>/content")
@auth.login_required
def paper_workspace_file_content(workspace_id, file_id):
    u = request.current_user
    workspace, item, _ = _authorized_workspace_file(workspace_id, file_id, u)
    if not workspace or not item:
        return jsonify({"error": "文件不存在"}), 404
    if not os.path.isfile(item["stored_path"]):
        return jsonify({"error": "文件已不在服务器"}), 410
    with open(item["stored_path"], "rb") as handle:
        raw = handle.read(200_001)
    if len(raw) > 200_000:
        return jsonify({"error": "文件超过 200 KB，请下载后查看"}), 413
    if b"\x00" in raw:
        return jsonify({"error": "二进制文件不支持在线预览"}), 415
    return jsonify({"content": raw.decode("utf-8", errors="replace"), "filename": item["original_name"]})


@bp.get("/paper/workspaces/<workspace_id>/files/<int:file_id>/download")
@auth.login_required
def paper_workspace_file_download(workspace_id, file_id):
    u = request.current_user
    workspace, item, _ = _authorized_workspace_file(workspace_id, file_id, u)
    if not workspace or not item:
        return jsonify({"error": "文件不存在"}), 404
    if not os.path.isfile(item["stored_path"]):
        return jsonify({"error": "文件已不在服务器"}), 410
    return send_file(item["stored_path"], as_attachment=True, download_name=item["original_name"])


@bp.get("/paper/workspaces/<workspace_id>/report")
@auth.login_required
def paper_workspace_report(workspace_id):
    u = request.current_user
    workspace = db.get_paper_workspace(workspace_id, include_details=False)
    exp = db.get_experiment(workspace["experiment_id"]) if workspace else None
    if not workspace or not _experiment_access(exp, u) or not workspace.get("report_md"):
        return jsonify({"error": "报告尚未生成"}), 404
    return Response(
        workspace["report_md"],
        mimetype="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=workspace-{workspace_id[:8]}-report.md"},
    )


@bp.post("/paper/workspaces/<workspace_id>/analysis/retry")
@auth.login_required
def retry_paper_workspace_analysis(workspace_id):
    u = request.current_user
    workspace = db.get_paper_workspace(workspace_id)
    if not workspace:
        return jsonify({"error": "工作区不存在"}), 404
    if workspace["user_id"] != u["id"]:
        return jsonify({"error": "仅实验所有者可以重新分析"}), 403
    if workspace["mode"] != "full":
        return jsonify({"error": "仅完整流程支持分析重试"}), 400
    if workspace["status"] in {"queued", "running"}:
        return jsonify({"error": "工作流仍在执行"}), 409
    task = paper_jobs.start_analysis_retry(
        current_app._get_current_object(), workspace, u, client_ip()
    )
    return jsonify({"task": task}), 202


@bp.post("/paper/workspaces/<workspace_id>/reclaim")
@auth.login_required
def reclaim_paper_workspace(workspace_id):
    u = request.current_user
    workspace = db.get_paper_workspace(workspace_id)
    if not workspace:
        return jsonify({"error": "工作区不存在"}), 404
    if workspace["user_id"] != u["id"]:
        return jsonify({"error": "仅实验所有者可以回收资源"}), 403
    if workspace["status"] in {"queued", "running"}:
        return jsonify({"error": "工作流仍在执行，暂不能回收"}), 409
    if workspace["resources_reclaimed"]:
        return jsonify({"ok": True, "deleted_pods": [], "workspace": workspace})
    try:
        deleted = k8s_client.delete_pods_by_experiment(workspace["experiment_id"])
    except Exception as exc:
        return jsonify({"error": f"资源回收失败：{exc}"}), 500
    db.update_paper_workspace(workspace_id, resources_reclaimed=True)
    db.add_paper_workspace_event(
        workspace_id, "lifecycle", "reclaimed", f"用户已回收 {len(deleted)} 个资源",
        data={"deleted_pods": deleted},
    )
    audit.log(
        u["id"], u["username"], "paper_workspace_reclaim",
        json.dumps({"workspace_id": workspace_id, "deleted_pods": deleted}),
    )
    updated = db.get_paper_workspace(workspace_id, user_id=u["id"])
    return jsonify({"ok": True, "deleted_pods": deleted, "workspace": _paper_workspace_payload(updated)})


@bp.delete("/paper/workspaces/<workspace_id>")
@auth.login_required
def delete_paper_workspace(workspace_id):
    """彻底删除单个工作区及其关联实验、Kubernetes 资源和存储产物。"""
    u = request.current_user
    workspace = db.get_paper_workspace(workspace_id, include_details=False)
    if not workspace:
        return jsonify({"error": "工作区不存在"}), 404
    if workspace["user_id"] != u["id"]:
        return jsonify({"error": "仅实验所有者可以删除工作区"}), 403
    if workspace["status"] in {"queued", "running"}:
        return jsonify({"error": "工作流仍在执行，暂不能删除"}), 409

    try:
        deleted_pods = k8s_client.delete_pods_by_experiment(workspace["experiment_id"])
    except Exception as exc:
        return jsonify({"error": f"清理 Pod 失败：{exc}"}), 500

    stored_paths = db.delete_experiment(workspace["experiment_id"])
    for path in stored_paths:
        try:
            os.remove(path)
        except OSError:
            pass

    workspace_root = os.path.realpath(
        os.path.join(UPLOAD_DIR, str(u["id"]), "paper", workspace["id"])
    )
    paper_root = os.path.realpath(os.path.join(UPLOAD_DIR, str(u["id"]), "paper"))
    if os.path.commonpath((paper_root, workspace_root)) == paper_root and workspace_root != paper_root:
        shutil.rmtree(workspace_root, ignore_errors=True)

    if session.get("current_experiment_id") == workspace["experiment_id"]:
        session["current_experiment_id"] = db.ensure_default_experiment(u["id"])
    audit.log(
        u["id"], u["username"], "paper_workspace_delete",
        json.dumps({"workspace_id": workspace_id, "deleted_pods": deleted_pods}),
        source_ip=client_ip(),
    )
    return jsonify({"ok": True, "deleted_pods": deleted_pods})


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
    audit.log(u["id"], u["username"], "upload_to_pod", f"{pod_name}:{pod_path}")
    return jsonify({"ok": True, "pod_path": pod_path})


# --------------------------------------------------------------------------------------
# 审计日志
# --------------------------------------------------------------------------------------

@bp.get("/logs")
@auth.login_required
def logs():
    u = request.current_user
    page = max(1, request.args.get("page", 1, type=int) or 1)
    page_size = min(100, max(10, request.args.get("page_size", 20, type=int) or 20))
    start_at = request.args.get("start_at", type=int)
    end_at = request.args.get("end_at", type=int)
    result = db.search_audit_logs(
        user_id=None if u["role"] == "admin" else u["id"],
        username=(request.args.get("username") or "").strip() if u["role"] == "admin" else "",
        action=(request.args.get("action") or "").strip(),
        keyword=(request.args.get("keyword") or "").strip()[:200],
        start_at=start_at,
        end_at=end_at,
        page=page,
        page_size=page_size,
    )
    return jsonify(result)


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
    audit.log(u["id"], u["username"], "create_experiment", f"{exp['id']}:{name}")
    exp["owner_username"] = u["username"]
    return jsonify(_summarize_experiment(exp))


@bp.get("/experiments/<int:exp_id>")
@auth.login_required
def get_experiment_detail(exp_id):
    u = request.current_user
    exp = db.get_experiment(exp_id)
    if not exp:
        return jsonify({"error": "实验不存在"}), 404
    access_role = _experiment_access(exp, u)
    if not access_role:
        return jsonify({"error": "无权查看他人实验"}), 403
    pods = k8s_client.list_pods_by_experiment(exp_id)
    if access_role == "collaborator":
        pods = [_sanitize_resource(item) for item in pods]
    counts = {"cloud": 0, "edge": 0, "device": 0}
    for p in pods:
        nt = p.get("node_type") or "edge"
        counts[nt] = counts.get(nt, 0) + 1
    paper_workspace = db.get_paper_workspace_for_experiment(
        exp_id,
    )
    collaborators = db.list_experiment_collaborators(exp_id)
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
            "collaborator_count": len(collaborators),
        },
        "pods": pods,
        "is_current": _current_experiment_id(u) == exp_id,
        "access_role": access_role,
        "paper_workspace": _paper_workspace_payload(
            paper_workspace, include_resources=False, access_role=access_role
        ),
    })


@bp.post("/experiments/<int:exp_id>/enter")
@auth.login_required
def enter_experiment(exp_id):
    u = request.current_user
    exp = db.get_experiment(exp_id)
    if not exp:
        return jsonify({"error": "实验不存在"}), 404
    access_role = _experiment_access(exp, u)
    if access_role not in {"owner", "admin"}:
        return jsonify({"error": "无权进入他人实验"}), 403
    session["current_experiment_id"] = exp_id
    audit.log(u["id"], u["username"], "enter_experiment", str(exp_id))
    return jsonify({"ok": True, "current_experiment_id": exp_id, "name": exp["name"]})


def _managed_experiment(exp_id, user):
    exp = db.get_experiment(exp_id)
    if not exp:
        return None, None
    access_role = _experiment_access(exp, user)
    return exp, access_role if access_role in {"owner", "admin"} else None


@bp.get("/experiments/<int:exp_id>/sharing")
@auth.login_required
def get_experiment_sharing(exp_id):
    u = request.current_user
    exp, manager_role = _managed_experiment(exp_id, u)
    if not exp:
        return jsonify({"error": "实验不存在"}), 404
    if not manager_role:
        return jsonify({"error": "仅实验所有者可以管理协作与分享"}), 403
    share = db.get_experiment_share(exp_id)
    return jsonify({
        "collaborators": db.list_experiment_collaborators(exp_id),
        "share": ({
            "enabled": True,
            "url": _share_url(share["token"]),
            "created_at": share["created_at"],
        } if share else {"enabled": False, "url": None}),
    })


@bp.post("/experiments/<int:exp_id>/collaborators")
@auth.login_required
def add_experiment_collaborator(exp_id):
    u = request.current_user
    exp, manager_role = _managed_experiment(exp_id, u)
    if not exp:
        return jsonify({"error": "实验不存在"}), 404
    if not manager_role:
        return jsonify({"error": "仅实验所有者可以添加协作者"}), 403
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()[:100]
    if not username:
        return jsonify({"error": "请输入协作者用户名"}), 400
    collaborator = db.find_user_by_username(username)
    if not collaborator:
        return jsonify({"error": "未找到该用户"}), 404
    if collaborator["id"] == exp["user_id"]:
        return jsonify({"error": "实验所有者无需重复添加"}), 400
    added = db.add_experiment_collaborator(exp_id, collaborator["id"], u["id"])
    audit.log(
        u["id"], u["username"], "experiment_collaborator_add",
        json.dumps({"experiment_id": exp_id, "collaborator": collaborator["username"]}),
        source_ip=client_ip(),
    )
    return jsonify({
        "added": added,
        "collaborators": db.list_experiment_collaborators(exp_id),
    })


@bp.delete("/experiments/<int:exp_id>/collaborators/<int:user_id>")
@auth.login_required
def remove_experiment_collaborator(exp_id, user_id):
    u = request.current_user
    exp, manager_role = _managed_experiment(exp_id, u)
    if not exp:
        return jsonify({"error": "实验不存在"}), 404
    if not manager_role:
        return jsonify({"error": "仅实验所有者可以移除协作者"}), 403
    removed = db.remove_experiment_collaborator(exp_id, user_id)
    if removed:
        audit.log(
            u["id"], u["username"], "experiment_collaborator_remove",
            json.dumps({"experiment_id": exp_id, "collaborator_user_id": user_id}),
            source_ip=client_ip(),
        )
    return jsonify({
        "removed": removed,
        "collaborators": db.list_experiment_collaborators(exp_id),
    })


@bp.post("/experiments/<int:exp_id>/share")
@auth.login_required
def enable_experiment_share(exp_id):
    u = request.current_user
    exp, manager_role = _managed_experiment(exp_id, u)
    if not exp:
        return jsonify({"error": "实验不存在"}), 404
    if not manager_role:
        return jsonify({"error": "仅实验所有者可以创建分享链接"}), 403
    share = db.ensure_experiment_share(exp_id, u["id"])
    audit.log(
        u["id"], u["username"], "experiment_share_enable",
        json.dumps({"experiment_id": exp_id}), source_ip=client_ip(),
    )
    return jsonify({
        "enabled": True,
        "url": _share_url(share["token"]),
        "created_at": share["created_at"],
    })


@bp.delete("/experiments/<int:exp_id>/share")
@auth.login_required
def disable_experiment_share(exp_id):
    u = request.current_user
    exp, manager_role = _managed_experiment(exp_id, u)
    if not exp:
        return jsonify({"error": "实验不存在"}), 404
    if not manager_role:
        return jsonify({"error": "仅实验所有者可以关闭分享链接"}), 403
    revoked = db.revoke_experiment_share(exp_id)
    if revoked:
        audit.log(
            u["id"], u["username"], "experiment_share_disable",
            json.dumps({"experiment_id": exp_id}), source_ip=client_ip(),
        )
    return jsonify({"enabled": False, "revoked": revoked})


def _public_workspace_payload(workspace):
    if not workspace:
        return None
    configuration = _sanitize_value(
        workspace.get("config_json") or {}, hide_ssh=True, hide_agent_trace=True
    )
    analysis = _sanitize_value(
        workspace.get("analysis_json") or {}, hide_ssh=True, hide_agent_trace=True
    )
    return {
        "id": workspace["id"],
        "experiment_id": workspace["experiment_id"],
        "name": workspace["name"],
        "goal": workspace["goal"],
        "mode": workspace["mode"],
        "status": workspace["status"],
        "stage": workspace["stage"],
        "config_json": configuration,
        "schedule_json": _sanitize_schedule(workspace.get("schedule_json"), hide_ssh=True),
        "analysis_json": analysis,
        "report_md": workspace.get("report_md") or "",
        "resources_reclaimed": workspace.get("resources_reclaimed", False),
        "created_at": workspace["created_at"],
        "updated_at": workspace["updated_at"],
        "finished_at": workspace.get("finished_at"),
        "files": [
            {
                "id": item["id"], "original_name": item["original_name"],
                "size": item["size"], "content_type": item["content_type"],
                "artifact_type": item["artifact_type"], "created_at": item["created_at"],
            }
            for item in workspace.get("files", [])
        ],
        "events": [
            {
                "id": item["id"], "phase": item["phase"],
                "event_type": item["event_type"], "content": item["content"],
                "created_at": item["created_at"],
            }
            for item in workspace.get("events", [])
        ],
    }


@bp.get("/public/experiments/shared/<token>")
def public_shared_experiment(token):
    exp = db.get_experiment_by_share_token(token)
    if not exp:
        return jsonify({"error": "分享链接无效或已关闭"}), 404
    workspace = db.get_paper_workspace_for_experiment(exp["id"])
    public_workspace = _public_workspace_payload(workspace)
    placements = ((public_workspace or {}).get("schedule_json") or {}).get("placements", [])
    counts = {
        tier: sum(item.get("node_type") == tier for item in placements)
        for tier in ("cloud", "edge", "device")
    }
    audit.log(
        None, "unknown", "experiment_share_view",
        json.dumps({"experiment_id": exp["id"]}), source_ip=client_ip(),
    )
    return jsonify({
        "experiment": {
            "id": exp["id"], "name": exp["name"],
            "description": exp.get("description") or "",
            "owner_username": exp.get("owner_username") or "",
            "created_at": exp["created_at"], "shared_at": exp["shared_at"],
            "cloud_count": counts["cloud"], "edge_count": counts["edge"],
            "device_count": counts["device"], "total_count": len(placements),
        },
        "paper_workspace": public_workspace,
        "read_only": True,
    })


@bp.get("/public/experiments/shared/<token>/files/<int:file_id>/download")
def public_shared_file_download(token, file_id):
    exp = db.get_experiment_by_share_token(token)
    workspace = db.get_paper_workspace_for_experiment(
        exp["id"], include_details=False
    ) if exp else None
    item = db.get_paper_workspace_file(file_id)
    if (
        not exp or not workspace or not item
        or item["workspace_id"] != workspace["id"]
    ):
        return jsonify({"error": "分享文件不存在"}), 404
    if not os.path.isfile(item["stored_path"]):
        return jsonify({"error": "文件已不在服务器"}), 410
    audit.log(
        None, "unknown", "experiment_share_download",
        json.dumps({"experiment_id": exp["id"], "file_id": file_id}),
        source_ip=client_ip(),
    )
    return send_file(
        item["stored_path"], as_attachment=True, download_name=item["original_name"]
    )


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
    stored_paths = db.delete_experiment(exp_id)
    for path in stored_paths:
        try:
            os.remove(path)
        except OSError:
            pass
    # 当前实验若被删，回退到该用户的默认实验（必要时新建）
    if session.get("current_experiment_id") == exp_id:
        session["current_experiment_id"] = db.ensure_default_experiment(u["id"])
    audit.log(u["id"], u["username"], "delete_experiment", f"{exp_id}:pods={len(deleted_pods)}")
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
        audit.log(u["id"], u["username"], "cordon_node", node_name)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.post("/admin/nodes/<node_name>/uncordon")
@auth.admin_required
def admin_uncordon_node(node_name):
    u = request.current_user
    try:
        k8s_client.uncordon_node(node_name)
        audit.log(u["id"], u["username"], "uncordon_node", node_name)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.delete("/admin/nodes/<node_name>")
@auth.admin_required
def admin_delete_node(node_name):
    u = request.current_user
    try:
        k8s_client.delete_node(node_name)
        audit.log(u["id"], u["username"], "delete_node", node_name)
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
    users = auth.list_users()
    unit_counts: dict[str, int] = {}
    units_available = True
    try:
        for pod in k8s_client.list_user_pods(request.current_user, all_users=True):
            owner_id = str(pod.get("owner_id") or "")
            unit_counts[owner_id] = unit_counts.get(owner_id, 0) + 1
    except Exception:
        units_available = False

    online_ids = presence.online_user_ids()
    for user in users:
        user["online"] = user["id"] in online_ids
        user["unit_count"] = unit_counts.get(str(user["id"]), 0) if units_available else None
    return jsonify({"users": users, "units_available": units_available})


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
    audit.log(u["id"], u["username"], "create_user", user["username"])
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
    audit.log(u["id"], u["username"], "change_password", f"uid={uid}")
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
    audit.log(u["id"], u["username"], "set_role", f"uid={uid} role={role}")
    return jsonify({"ok": True})


@bp.delete("/admin/users/<int:uid>")
@auth.admin_required
def admin_delete_user(uid):
    u = request.current_user
    auth.delete_user(uid)
    audit.log(u["id"], u["username"], "delete_user", str(uid))
    return jsonify({"ok": True})
