"""LangGraph Agent 用到的工具集合。

每个工具都使用 @tool 装饰器封装：
- 工具内部通过线程局部变量获取 当前用户 上下文（CURRENT_USER）
- 普通用户工具受权限校验保护：只能操作自己拥有的资源
- 管理员工具：节点查询、节点删除
"""
from __future__ import annotations

import contextvars
import json
import os
import re
from typing import Optional

from langchain_core.tools import tool

from . import db, k8s_client
from .config import UPLOAD_DIR

# 使用 ContextVar 代替 threading.local，确保在 LangGraph 线程池中也能正确继承上下文
_user_ctx: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("current_user", default=None)
_file_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("uploaded_file", default=None)
_exp_ctx: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("current_experiment", default=None)


def set_user(user: dict, uploaded_file: Optional[str] = None, experiment_id: Optional[int] = None):
    _user_ctx.set(user)
    _file_ctx.set(uploaded_file)
    _exp_ctx.set(experiment_id)


def _exp() -> Optional[int]:
    return _exp_ctx.get()


def _user() -> dict:
    u = _user_ctx.get()
    if not u:
        raise RuntimeError("用户会话已失效，请刷新页面重新登录后再试")
    return u


def _is_admin() -> bool:
    return _user().get("role") == "admin"


def _audit(action: str, detail):
    u = _user()
    db.log_audit(u["id"], u["username"], action, detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False))


# --------------------------------------------------------------------------------------
# 普通用户工具
# --------------------------------------------------------------------------------------

@tool
def list_my_resources() -> str:
    """查看当前用户名下所有的 Pod / 容器资源（名称、节点、节点类型、架构、状态、SSH 信息）。"""
    pods = k8s_client.list_user_pods(_user())
    if not pods:
        return "你当前没有任何资源。"
    lines = []
    for p in pods:
        ssh = ""
        if p.get("ssh_port"):
            ssh = f" | SSH: ssh -p {p['ssh_port']} {p.get('ssh_user','root')}@<节点IP> 密码:{p.get('ssh_password','')}"
        gpu = f" | GPU:{p.get('gpu')}" if p.get("gpu") else ""
        nt = p.get("node_type", "edge")
        lines.append(
            f"- {p['name']} | 状态:{p['phase']} | 节点:{p['node']}[{nt}] | 架构:{p['arch']} | 镜像:{p['image']}{gpu}{ssh}"
        )
    return "你名下的资源：\n" + "\n".join(lines)


@tool
def create_ssh_container(
    arch: Optional[str] = None,
    hostname: Optional[str] = None,
    image: Optional[str] = None,
    cpu: Optional[str] = None,
    memory: Optional[str] = None,
    count: int = 1,
    node_type: Optional[str] = None,
    gpu: int = 0,
) -> str:
    """创建支持 SSH 登录的 Linux 容器。所有参数均可选，可自由组合：
    - image（如 ubuntu:20.04 / docker.io/library/ubuntu:20.04）：指定容器镜像
    - arch（amd64/arm64/riscv64/riscv/arm 等）：通过 kubernetes.io/arch 标签调度到匹配架构的节点
    - node_type（cloud/edge/device）：通过 node-type 标签调度到云/边缘/端设备节点
    - hostname：固定调度到指定节点（主机名），优先级最高
    - arch 与 node_type 可同时指定，取交集（如 riscv64 架构的云节点）
    - gpu（整数，默认 0）：申请 nvidia.com/gpu 数量。>0 时会自动只调度到装了
      k8s-device-plugin 的节点，并强制使用 docker.io/nvidia/cuda:11.8.0-runtime-ubuntu20.04
      镜像（即此时 image 参数会被忽略）。
    - 不填任何参数 → 在任意可用节点上用默认镜像创建
    可一次创建多个（count 默认 1，上限 10）。
    """
    count = max(1, min(int(count or 1), 10))
    gpu = max(0, int(gpu or 0))
    out = []
    for _ in range(count):
        info = k8s_client.create_ssh_pod(
            _user(), arch=arch, hostname=hostname, image=image,
            cpu=cpu, memory=memory, node_type=node_type,
            experiment_id=_exp(), gpu=gpu,
        )
        _audit("create_ssh_pod", info)
        out.append(info)
    msg = ["✅ 已创建 {} 个 SSH 容器：".format(len(out))]
    for o in out:
        nt = o.get("node_type", "edge")
        gpu_part = f" GPU:{o.get('gpu')}" if o.get("gpu") else ""
        msg.append(
            f"- {o['pod_name']} 节点:{o['node']}[{nt}] 架构:{o['arch']} 镜像:{o['image']}{gpu_part}\n"
            f"  连接:{o['ssh_command']}  密码:{o['ssh_password']}\n"
            f"  说明:容器启动会安装 sshd，首次连接可能需要等待 30-60 秒"
            + ("，GPU 镜像较大首次拉取可能更久" if o.get("gpu") else "")
        )
    return "\n".join(msg)


@tool
def delete_my_pod(pod_name: str) -> str:
    """根据 Pod 名称删除当前用户名下的容器/Pod。"""
    try:
        k8s_client.delete_pod(pod_name, _user())
        _audit("delete_pod", pod_name)
        return f"✅ 已删除 {pod_name}"
    except PermissionError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ 删除失败：{e}"


@tool
def delete_all_my_pods() -> str:
    """一键删除当前用户所有 Pod（谨慎使用）。"""
    pods = k8s_client.list_user_pods(_user())
    deleted = []
    for p in pods:
        try:
            k8s_client.delete_pod(p["name"], _user())
            deleted.append(p["name"])
        except Exception:
            pass
    _audit("delete_all_my_pods", deleted)
    return f"✅ 已删除 {len(deleted)} 个 Pod：{', '.join(deleted) if deleted else '无'}"


@tool
def exec_command_in_my_pod(pod_name: str, command: str) -> str:
    """在自己拥有的 Pod 中执行一条 shell 命令并返回输出（非交互、超时 60s）。"""
    try:
        k8s_client.assert_pod_owned(pod_name, _user())
    except Exception as e:
        return f"❌ {e}"
    res = k8s_client.exec_in_pod(pod_name, ["/bin/sh", "-c", command], timeout=60)
    _audit("exec_in_pod", {"pod": pod_name, "cmd": command})
    out = res.get("stdout", "")
    err = res.get("stderr", "")
    if not out and not err:
        return "（无输出）"
    return f"stdout:\n{out}\n\nstderr:\n{err}"


@tool
def run_uploaded_python(
    hostname: Optional[str] = None,
    arch: Optional[str] = None,
    image: str = "python:3.11-slim",
    timeout: int = 120,
) -> str:
    """在临时容器里运行用户最近一次上传的 Python 脚本，并返回执行结果。
    可选指定目标节点 hostname、架构 arch、Python 镜像 image、超时时间(秒)。
    临时容器执行完毕会被自动销毁。"""
    code_path = _file_ctx.get()
    if not code_path or not os.path.exists(code_path):
        return "❌ 当前没有可执行的上传脚本，请先在前端上传 .py 文件后再发指令。"
    if not code_path.endswith(".py"):
        return "❌ 上传的文件不是 .py 文件。"
    try:
        res = k8s_client.run_python_oneshot(
            _user(), code_path,
            hostname=hostname, arch=arch, image=image, timeout=int(timeout),
            experiment_id=_exp(),
        )
    except Exception as e:
        return f"❌ 执行失败：{e}"
    _audit("run_python", {"node": res.get("node"), "pod": res.get("pod_name")})
    out = res.get("stdout", "")
    err = res.get("stderr", "")
    text = f"✅ 执行完毕（节点:{res.get('node')}，临时 Pod:{res.get('pod_name')}）\n\n--- stdout ---\n{out}"
    if err:
        text += f"\n\n--- stderr ---\n{err}"
    return text


@tool
def cluster_overview() -> str:
    """查看集群基础信息：版本、节点数、就绪节点数、namespace。"""
    info = k8s_client.cluster_info()
    return (
        f"集群版本:{info['version']} | 节点总数:{info['node_count']} | "
        f"就绪:{info['ready_nodes']} | namespace:{info['namespace']}"
    )


# --------------------------------------------------------------------------------------
# 管理员工具
# --------------------------------------------------------------------------------------

@tool
def admin_list_nodes() -> str:
    """[管理员] 列出集群所有节点：名称、节点类型(cloud/edge/device)、架构、Ready 状态、IP、版本。"""
    if not _is_admin():
        return "❌ 仅管理员可调用本工具。"
    nodes = k8s_client.list_nodes()
    lines = ["集群节点列表："]
    for n in nodes:
        lines.append(
            f"- {n['name']} | 类型:{n.get('node_type','edge')} | hostname:{n['hostname']} | "
            f"arch:{n['arch']} | Ready:{n['ready']} | IP:{n['internal_ip']} | kubelet:{n['kubelet_version']}"
        )
    return "\n".join(lines)


@tool
def admin_delete_node(node_name: str) -> str:
    """[管理员] 从集群中删除一个节点（仅删除 K8s Node 对象，不卸载机器）。"""
    if not _is_admin():
        return "❌ 仅管理员可调用本工具。"
    try:
        k8s_client.delete_node(node_name)
        _audit("delete_node", node_name)
        return f"✅ 已删除节点 {node_name}"
    except Exception as e:
        return f"❌ 删除失败：{e}"


@tool
def admin_list_all_pods() -> str:
    """[管理员] 列出所有用户的 smart-kube Pod。"""
    if not _is_admin():
        return "❌ 仅管理员可调用本工具。"
    pods = k8s_client.list_user_pods(_user(), all_users=True)
    if not pods:
        return "暂无 Units。"
    lines = ["所有 Pod："]
    for p in pods:
        lines.append(
            f"- {p['name']} | 所属:{p.get('owner_username')} | 节点:{p['node']} | "
            f"状态:{p['phase']} | 架构:{p['arch']}"
        )
    return "\n".join(lines)


# 工具注册：根据角色返回不同工具集
USER_TOOLS = [
    list_my_resources,
    create_ssh_container,
    delete_my_pod,
    delete_all_my_pods,
    exec_command_in_my_pod,
    run_uploaded_python,
    cluster_overview,
]

ADMIN_TOOLS = USER_TOOLS + [
    admin_list_nodes,
    admin_delete_node,
    admin_list_all_pods,
]


def tools_for(user: dict):
    return ADMIN_TOOLS if user.get("role") == "admin" else USER_TOOLS


# --------------------------------------------------------------------------------------
# 简易自然语言预解析（兜底：当 LLM 不可用时也尽量满足核心场景）
# 注：这是一个保底逻辑，正常情况都走 LangGraph + LLM 的工具调用路径。
# --------------------------------------------------------------------------------------

ARCH_PATTERN = re.compile(r"\b(riscv64|riscv|arm64|aarch64|arm|x86_64|x86|amd64)\b", re.I)
COUNT_PATTERN = re.compile(r"(\d+)\s*个")
HOSTNAME_PATTERN = re.compile(r"(?:节点|hostname|主机|机器)[^a-zA-Z0-9_-]{0,4}([a-zA-Z][\w\-.]*)", re.I)
# 匹配 GPU 数量：如"2张GPU"、"1块gpu"、"3 gpu"、"GPU=2"、"--gpu 1"
GPU_COUNT_PATTERN = re.compile(
    r"(?:(\d+)\s*(?:张|块|个|片)?\s*(?:gpu|nvidia|显卡|cuda)|(?:gpu|nvidia|显卡|cuda)[^0-9]{0,4}(\d+))",
    re.I,
)
GPU_KEYWORD_PATTERN = re.compile(r"\b(gpu|nvidia|cuda|显卡)\b", re.I)
# 匹配镜像名：registry/image:tag 或 image:tag（tag 必须含点/字母，避免误匹配中文数字）
IMAGE_PATTERN = re.compile(
    r"("
    r"(?:[a-zA-Z0-9][a-zA-Z0-9.\-_]*\.(?:io|com|org|net|cn)/[^\s]+"  # registry.io/xxx
    r"|[a-zA-Z0-9][a-zA-Z0-9.\-_]*/[a-zA-Z0-9.\-_/]+(?::[a-zA-Z0-9.\-_]+)?"  # org/image:tag
    r"|(?:ubuntu|debian|centos|alpine|python|nginx|redis|mysql|node|golang|java):[a-zA-Z0-9.\-_]+"  # 常见镜像:tag
    r")"
    r")"
)

# 云边端节点类型关键词 → node-type 标签值
_NODE_TYPE_KEYWORDS: list[tuple[list[str], str]] = [
    (["cloud", "云节点", "云端", "云上", "云服务器"], "cloud"),
    (["edge", "边缘节点", "边缘", "边端"], "edge"),
    (["device", "端节点", "设备节点", "设备", "终端"], "device"),
]


def _detect_node_type(text: str) -> Optional[str]:
    """从文本中识别云/边/端节点类型意图。"""
    t = text.lower()
    for keywords, nt in _NODE_TYPE_KEYWORDS:
        if any(k in t for k in keywords):
            return nt
    if re.search(r"在云|到云|云上", t):
        return "cloud"
    if re.search(r"在边|到边", t):
        return "edge"
    if re.search(r"在端|到端|设备上", t):
        return "device"
    return None


def _detect_gpu(text: str) -> int:
    """从文本中识别 GPU 申请数量；命中 GPU 关键字但未带数字时默认 1。"""
    m = GPU_COUNT_PATTERN.search(text)
    if m:
        n = m.group(1) or m.group(2)
        try:
            return max(1, int(n))
        except (TypeError, ValueError):
            pass
    if GPU_KEYWORD_PATTERN.search(text):
        return 1
    return 0


def fallback_parse(text: str) -> Optional[dict]:
    """无 LLM 时基于规则解析常见指令。"""
    t = text.strip()
    arch_m = ARCH_PATTERN.search(t)
    count_m = COUNT_PATTERN.search(t)
    host_m = HOSTNAME_PATTERN.search(t)
    image_m = IMAGE_PATTERN.search(t)
    arch = arch_m.group(1).lower() if arch_m else None
    count = int(count_m.group(1)) if count_m else 1
    hostname = host_m.group(1) if host_m else None
    image = image_m.group(1) if image_m else None
    node_type = _detect_node_type(t)
    gpu = _detect_gpu(t)
    if any(k in t for k in ["创建", "新建", "拉起", "启动一个", "起一个", "起一批"]) or (
        image and not any(k in t for k in ["删除", "查看", "列出"])
    ) or gpu > 0:
        return {"action": "create_ssh", "arch": arch, "count": count, "hostname": hostname, "image": image, "node_type": node_type, "gpu": gpu}
    if any(k in t for k in ["列出", "查看", "我的资源", "查我", "我有哪些"]):
        return {"action": "list"}
    if "删除" in t or "销毁" in t or "干掉" in t:
        m = re.search(r"([a-z][a-z0-9-]{2,})", t)
        return {"action": "delete", "pod_name": m.group(1) if m else None}
    if "节点" in t and ("查看" in t or "列出" in t):
        return {"action": "nodes"}
    if "执行" in t and "python" in t.lower():
        return {"action": "run_python", "hostname": hostname, "arch": arch}
    return None
