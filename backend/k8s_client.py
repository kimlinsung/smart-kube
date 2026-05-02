"""Kubernetes 客户端封装。

负责：
1. 加载 kubeconfig（或 in-cluster 配置）
2. 命名空间确保存在
3. 节点列表查询、节点删除（管理员）
4. 用户隔离的 Pod 创建/列表/删除
5. SSH NodePort 端口分配与 Service 创建
6. 容器内执行命令（exec stream）
7. 拷贝文件到 Pod
8. 临时 Python 容器一次性执行代码
"""
from __future__ import annotations

import io
import logging
import os
import random
import tarfile
import time
from typing import Iterable, Optional

from kubernetes import client, config, stream
from kubernetes.client import ApiException

from . import db
from .config import (
    ARCH_IMAGES,
    KUBECONFIG,
    NAMESPACE,
    RES_CONF,
    SSH_CONF,
)

log = logging.getLogger(__name__)

_LABEL_OWNER = "smartkube/owner"
_LABEL_APP = "smartkube/app"
_LABEL_KIND = "smartkube/kind"  # ssh / exec / generic

# 用户输入的架构名 → kubernetes.io/arch 标准值
_ARCH_ALIASES: dict[str, str] = {
    "riscv": "riscv64",
    "riscv64": "riscv64",
    "arm64": "arm64",
    "arm": "arm64",
    "aarch64": "arm64",
    "amd64": "amd64",
    "x86_64": "amd64",
    "x86": "amd64",
    "386": "386",
    "i386": "386",
    "i686": "386",
}


def _normalize_arch(arch: str) -> str:
    """将用户输入的架构名规范化为 kubernetes.io/arch 标准值。"""
    return _ARCH_ALIASES.get(arch.lower(), arch.lower())


# --------------------------------------------------------------------------------------
# 客户端初始化
# --------------------------------------------------------------------------------------

def _load_kube():
    if KUBECONFIG and os.path.exists(KUBECONFIG):
        config.load_kube_config(config_file=KUBECONFIG)
    else:
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()


_load_kube()
core_v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()
version_api = client.VersionApi()


def ensure_namespace():
    try:
        core_v1.read_namespace(NAMESPACE)
    except ApiException as e:
        if e.status == 404:
            core_v1.create_namespace(client.V1Namespace(metadata=client.V1ObjectMeta(name=NAMESPACE)))
        else:
            raise


# --------------------------------------------------------------------------------------
# 节点
# --------------------------------------------------------------------------------------

def list_nodes() -> list[dict]:
    res = []
    nodes = core_v1.list_node().items
    for n in nodes:
        labels = n.metadata.labels or {}
        cond_ready = "Unknown"
        for c in (n.status.conditions or []):
            if c.type == "Ready":
                cond_ready = c.status
        res.append({
            "name": n.metadata.name,
            "arch": labels.get("kubernetes.io/arch", "unknown"),
            "os": labels.get("kubernetes.io/os", "unknown"),
            "hostname": labels.get("kubernetes.io/hostname", n.metadata.name),
            "node_type": labels.get("node-type", "edge"),  # cloud / edge / device，默认 edge
            "ready": cond_ready,
            "internal_ip": next((a.address for a in (n.status.addresses or []) if a.type == "InternalIP"), ""),
            "kubelet_version": (n.status.node_info.kubelet_version if n.status.node_info else ""),
            "capacity": dict(n.status.capacity or {}),
            "allocatable": dict(n.status.allocatable or {}),
            "labels": labels,
        })
    return res


def delete_node(name: str):
    core_v1.delete_node(name)


def cluster_info() -> dict:
    try:
        v = version_api.get_code()
        version = v.git_version
    except Exception:
        version = "unknown"
    nodes = list_nodes()
    return {
        "version": version,
        "node_count": len(nodes),
        "ready_nodes": sum(1 for n in nodes if n["ready"] == "True"),
        "namespace": NAMESPACE,
    }


def find_node_by_arch_or_hostname(
    arch: Optional[str] = None,
    hostname: Optional[str] = None,
    node_type: Optional[str] = None,
) -> Optional[dict]:
    """根据条件筛选一个 Ready 节点。
    hostname 精确匹配优先级最高；arch 规范化后匹配 kubernetes.io/arch；
    node_type 匹配 node-type 标签（cloud/edge/device）。
    任何条件若指定但无匹配节点，则返回 None（不静默兜底）。
    """
    nodes = list_nodes()
    if hostname:
        for n in nodes:
            if n["hostname"] == hostname or n["name"] == hostname:
                return n
        return None

    candidates = [n for n in nodes if n["ready"] == "True"]
    if arch:
        arch_norm = _normalize_arch(arch)
        candidates = [n for n in candidates if _normalize_arch(n["arch"]) == arch_norm]
    if node_type:
        candidates = [n for n in candidates if n.get("node_type", "edge") == node_type]

    if candidates:
        return candidates[0]
    if arch or node_type:
        return None  # 有条件但无匹配，不静默兜底
    return None


# --------------------------------------------------------------------------------------
# Pod / Service
# --------------------------------------------------------------------------------------

def _resolve_image(arch: Optional[str], image: Optional[str]) -> str:
    if image:
        return image
    if arch:
        return ARCH_IMAGES.get(arch.lower()) or ARCH_IMAGES.get("amd64") or "ubuntu:22.04"
    return ARCH_IMAGES.get("amd64") or "ubuntu:22.04"


def _make_pod_name(prefix: str, owner: str) -> str:
    rnd = "{:04x}".format(random.randint(0, 0xFFFF))
    base = f"{prefix}-{owner.lower()}-{int(time.time()) % 100000}-{rnd}"
    return base.replace("_", "-")[:50]


def _allocate_ssh_port(pod_name: str, user_id: int) -> int:
    """从配置范围内分配一个未占用的 NodePort。"""
    start = SSH_CONF.get("port_range_start", 30000)
    end = SSH_CONF.get("port_range_end", 32000)
    with db.cursor() as cur:
        cur.execute("SELECT port FROM ssh_ports")
        used = {r["port"] for r in cur.fetchall()}
    candidates = [p for p in range(start, end + 1) if p not in used]
    if not candidates:
        raise RuntimeError("SSH NodePort 端口已耗尽")
    port = random.choice(candidates)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO ssh_ports(port, pod_name, user_id, allocated_at) VALUES(?,?,?,?)",
            (port, pod_name, user_id, int(time.time())),
        )
    return port


def _release_ssh_port(pod_name: str):
    with db.cursor() as cur:
        cur.execute("DELETE FROM ssh_ports WHERE pod_name=?", (pod_name,))


def _build_pod_spec(
    containers, restart_policy, hostname, arch_canonical, node,
    node_type: Optional[str] = None, **kwargs
) -> client.V1PodSpec:
    """构建 PodSpec。
    hostname → node_name 固定调度；
    arch/node_type → nodeSelector 标签调度（可同时指定）；
    均未指定 → 无约束，调度器自由分配。
    """
    spec = client.V1PodSpec(containers=containers, restart_policy=restart_policy, **kwargs)
    if hostname:
        spec.node_name = node["name"]
    else:
        selector = {}
        if arch_canonical:
            selector["kubernetes.io/arch"] = arch_canonical
        if node_type:
            selector["node-type"] = node_type
        if selector:
            spec.node_selector = selector
    return spec


def create_ssh_pod(
    user: dict,
    arch: Optional[str] = None,
    hostname: Optional[str] = None,
    image: Optional[str] = None,
    cpu: Optional[str] = None,
    memory: Optional[str] = None,
    name_prefix: str = "ssh",
    node_type: Optional[str] = None,
) -> dict:
    """创建一个安装并启动 SSHD 的 Pod，并通过 NodePort Service 暴露 22 端口。

    返回：包含 pod_name、node、node_type、ssh_host、ssh_port、ssh_user、ssh_password 的 dict。
    """
    ensure_namespace()
    arch_canonical = _normalize_arch(arch) if arch else None
    node = find_node_by_arch_or_hostname(arch=arch_canonical, hostname=hostname, node_type=node_type)
    if not node:
        parts = []
        if hostname:   parts.append(f"hostname={hostname}")
        if arch_canonical: parts.append(f"arch={arch_canonical}")
        if node_type:  parts.append(f"node-type={node_type}")
        cond = "，".join(parts) if parts else "（集群无就绪节点）"
        raise RuntimeError(f"未找到符合条件的就绪节点：{cond}")

    image_resolved = _resolve_image(arch_canonical or node["arch"], image)
    owner_label = str(user["id"])
    pod_name = _make_pod_name(name_prefix, user["username"])
    root_pwd = SSH_CONF.get("default_root_password", "smartkube")
    nodeport = _allocate_ssh_port(pod_name, user["id"])

    # 启动脚本：安装并启动 sshd（兼容 debian/ubuntu 系镜像）
    start_cmd = (
        "set -e; "
        "if ! command -v sshd >/dev/null 2>&1; then "
        "  (apt-get update && apt-get install -y --no-install-recommends openssh-server) "
        "  || (apk add --no-cache openssh) "
        "  || (yum install -y openssh-server) || true; "
        "fi; "
        "mkdir -p /var/run/sshd /run/sshd; "
        f"echo 'root:{root_pwd}' | chpasswd; "
        "sed -i 's/^#\\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config || true; "
        "sed -i 's/^#\\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config || true; "
        "ssh-keygen -A 2>/dev/null || true; "
        "echo '[smart-kube] ssh ready'; "
        "exec /usr/sbin/sshd -D -e"
    )

    container = client.V1Container(
        name="main",
        image=image_resolved,
        image_pull_policy="IfNotPresent",
        command=["/bin/sh", "-c", start_cmd],
        ports=[client.V1ContainerPort(container_port=22)],
        resources=client.V1ResourceRequirements(
            requests={
                "cpu": cpu or RES_CONF.get("default_cpu_request", "100m"),
                "memory": memory or RES_CONF.get("default_memory_request", "128Mi"),
            },
            limits={
                "cpu": cpu or RES_CONF.get("default_cpu_limit", "1"),
                "memory": memory or RES_CONF.get("default_memory_limit", "1Gi"),
            },
        ),
    )

    pod = client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=pod_name,
            namespace=NAMESPACE,
            labels={
                _LABEL_OWNER: owner_label,
                _LABEL_APP: pod_name,
                _LABEL_KIND: "ssh",
            },
            annotations={
                "smartkube/owner-username": user["username"],
                "smartkube/arch": arch_canonical or node["arch"] or "",
                "smartkube/node-type": node.get("node_type", "edge"),
                "smartkube/image": image_resolved,
                "smartkube/ssh-port": str(nodeport),
                "smartkube/ssh-user": "root",
                "smartkube/ssh-password": root_pwd,
            },
        ),
        spec=_build_pod_spec(
            containers=[container],
            restart_policy="Always",
            hostname=hostname,
            arch_canonical=arch_canonical,
            node=node,
            node_type=node_type,
        ),
    )

    try:
        core_v1.create_namespaced_pod(NAMESPACE, pod)
    except ApiException as e:
        _release_ssh_port(pod_name)
        raise RuntimeError(f"Pod 创建失败：{e.reason}") from e

    svc = client.V1Service(
        metadata=client.V1ObjectMeta(
            name=pod_name,
            namespace=NAMESPACE,
            labels={_LABEL_OWNER: owner_label, _LABEL_APP: pod_name},
        ),
        spec=client.V1ServiceSpec(
            type="NodePort",
            selector={_LABEL_APP: pod_name},
            ports=[client.V1ServicePort(port=22, target_port=22, node_port=nodeport, protocol="TCP")],
        ),
    )
    try:
        core_v1.create_namespaced_service(NAMESPACE, svc)
    except ApiException as e:
        # 清理 Pod 和端口分配
        try:
            core_v1.delete_namespaced_pod(pod_name, NAMESPACE)
        except Exception:
            pass
        _release_ssh_port(pod_name)
        raise RuntimeError(f"SSH Service 创建失败：{e.reason}") from e

    return {
        "pod_name": pod_name,
        "node": node["name"],
        "arch": arch_canonical or node["arch"],
        "node_type": node.get("node_type", "edge"),
        "image": image_resolved,
        "ssh_host": node["internal_ip"] or node["hostname"] or node["name"],
        "ssh_port": nodeport,
        "ssh_user": "root",
        "ssh_password": root_pwd,
        "ssh_command": f"ssh -p {nodeport} root@{node['internal_ip'] or node['name']}",
    }


def list_user_pods(user: dict, all_users: bool = False) -> list[dict]:
    sel = "" if all_users else f"{_LABEL_OWNER}={user['id']}"
    pods = core_v1.list_namespaced_pod(NAMESPACE, label_selector=sel).items

    # 构建节点名 → node-type 的快速查找表
    node_type_map: dict[str, str] = {}
    try:
        for n in core_v1.list_node().items:
            labels = n.metadata.labels or {}
            node_type_map[n.metadata.name] = labels.get("node-type", "edge")
    except Exception:
        pass

    out = []
    for p in pods:
        ann = p.metadata.annotations or {}
        node_name = p.spec.node_name or ""
        # 优先使用创建时写入的注解，回退到实时节点标签
        node_type = ann.get("smartkube/node-type") or node_type_map.get(node_name, "edge")
        out.append({
            "name": p.metadata.name,
            "namespace": p.metadata.namespace,
            "owner_id": (p.metadata.labels or {}).get(_LABEL_OWNER),
            "owner_username": ann.get("smartkube/owner-username"),
            "kind": (p.metadata.labels or {}).get(_LABEL_KIND, "generic"),
            "node": node_name,
            "arch": ann.get("smartkube/arch", ""),
            "node_type": node_type,
            "image": ann.get("smartkube/image", ""),
            "phase": p.status.phase,
            "created_at": p.metadata.creation_timestamp.isoformat() if p.metadata.creation_timestamp else "",
            "ssh_port": ann.get("smartkube/ssh-port"),
            "ssh_user": ann.get("smartkube/ssh-user"),
            "ssh_password": ann.get("smartkube/ssh-password"),
        })
    return out


def get_pod(pod_name: str) -> Optional[dict]:
    try:
        p = core_v1.read_namespaced_pod(pod_name, NAMESPACE)
    except ApiException:
        return None
    ann = p.metadata.annotations or {}
    return {
        "name": p.metadata.name,
        "owner_id": (p.metadata.labels or {}).get(_LABEL_OWNER),
        "kind": (p.metadata.labels or {}).get(_LABEL_KIND, "generic"),
        "node": p.spec.node_name,
        "phase": p.status.phase,
        "ssh_port": ann.get("smartkube/ssh-port"),
    }


def assert_pod_owned(pod_name: str, user: dict) -> dict:
    """普通用户只能操作自己的 Pod；管理员可以操作任意 Pod。"""
    p = get_pod(pod_name)
    if not p:
        raise RuntimeError(f"Pod {pod_name} 不存在")
    if user["role"] != "admin" and str(p["owner_id"]) != str(user["id"]):
        raise PermissionError(f"无权限操作他人 Pod：{pod_name}")
    return p


def delete_pod(pod_name: str, user: dict):
    assert_pod_owned(pod_name, user)
    try:
        core_v1.delete_namespaced_pod(pod_name, NAMESPACE)
    except ApiException as e:
        if e.status != 404:
            raise
    try:
        core_v1.delete_namespaced_service(pod_name, NAMESPACE)
    except ApiException as e:
        if e.status != 404:
            pass
    _release_ssh_port(pod_name)


# --------------------------------------------------------------------------------------
# Pod 内 exec / 文件传输
# --------------------------------------------------------------------------------------

def exec_in_pod(pod_name: str, command: list[str], timeout: int = 60) -> dict:
    """非交互执行命令并返回 stdout/stderr。"""
    resp = stream.stream(
        core_v1.connect_get_namespaced_pod_exec,
        pod_name,
        NAMESPACE,
        command=command,
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
        _preload_content=False,
    )
    out, err = [], []
    deadline = time.time() + timeout
    while resp.is_open():
        resp.update(timeout=1)
        if resp.peek_stdout():
            out.append(resp.read_stdout())
        if resp.peek_stderr():
            err.append(resp.read_stderr())
        if time.time() > deadline:
            break
    resp.close()
    return {"stdout": "".join(out), "stderr": "".join(err)}


def open_exec_stream(pod_name: str, command: Iterable[str] = ("/bin/sh", "-l")):
    """打开一个交互式 exec 流，用于 Web Shell。"""
    return stream.stream(
        core_v1.connect_get_namespaced_pod_exec,
        pod_name,
        NAMESPACE,
        command=list(command),
        stderr=True,
        stdin=True,
        stdout=True,
        tty=True,
        _preload_content=False,
    )


def copy_to_pod(pod_name: str, src_path: str, dest_dir: str = "/tmp", filename: Optional[str] = None) -> str:
    """把本地文件 cp 进 Pod，返回 Pod 内的最终路径。"""
    fname = filename or os.path.basename(src_path)
    pod_path = os.path.join(dest_dir, fname)

    # 通过 tar 流写入 stdin
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(src_path, arcname=fname)
    buf.seek(0)

    resp = stream.stream(
        core_v1.connect_get_namespaced_pod_exec,
        pod_name,
        NAMESPACE,
        command=["tar", "xf", "-", "-C", dest_dir],
        stderr=True, stdin=True, stdout=True, tty=False,
        _preload_content=False,
    )
    try:
        while resp.is_open():
            resp.update(timeout=1)
            chunk = buf.read(4096)
            if not chunk:
                break
            resp.write_stdin(chunk)
    finally:
        resp.close()
    return pod_path


# --------------------------------------------------------------------------------------
# 临时 Python 容器执行
# --------------------------------------------------------------------------------------

def run_python_oneshot(
    user: dict,
    code_path: str,
    hostname: Optional[str] = None,
    arch: Optional[str] = None,
    image: str = "python:3.11-slim",
    timeout: int = 120,
    node_type: Optional[str] = None,
) -> dict:
    """拉起一个临时 python Pod，挂入代码并执行，运行完毕后销毁。返回输出。"""
    ensure_namespace()
    arch_canonical = _normalize_arch(arch) if arch else None
    node = find_node_by_arch_or_hostname(arch=arch_canonical, hostname=hostname, node_type=node_type)
    if not node:
        raise RuntimeError("未找到可用节点用于 Python 执行")
    name = _make_pod_name("pyexec", user["username"])

    # 让容器先睡眠等待我们 cp 文件后 exec 触发执行
    container = client.V1Container(
        name="main",
        image=image,
        image_pull_policy="IfNotPresent",
        command=["/bin/sh", "-c", f"sleep {timeout + 60}"],
        resources=client.V1ResourceRequirements(
            requests={"cpu": "100m", "memory": "128Mi"},
            limits={"cpu": "1", "memory": "1Gi"},
        ),
    )
    pod = client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=NAMESPACE,
            labels={
                _LABEL_OWNER: str(user["id"]),
                _LABEL_APP: name,
                _LABEL_KIND: "exec",
            },
            annotations={
                "smartkube/owner-username": user["username"],
                "smartkube/arch": arch_canonical or node["arch"] or "",
                "smartkube/node-type": node.get("node_type", "edge"),
                "smartkube/image": image,
            },
        ),
        spec=_build_pod_spec(
            containers=[container],
            restart_policy="Never",
            hostname=hostname,
            arch_canonical=arch_canonical,
            node=node,
            node_type=node_type,
        ),
    )
    core_v1.create_namespaced_pod(NAMESPACE, pod)

    # 等 Pod Running
    deadline = time.time() + 90
    phase = ""
    while time.time() < deadline:
        try:
            p = core_v1.read_namespaced_pod(name, NAMESPACE)
            phase = p.status.phase
        except ApiException:
            phase = ""
        if phase == "Running":
            break
        time.sleep(1)
    if phase != "Running":
        try:
            core_v1.delete_namespaced_pod(name, NAMESPACE)
        except Exception:
            pass
        raise RuntimeError(f"临时 Python Pod 未能进入 Running，状态：{phase}")

    try:
        copy_to_pod(name, code_path, dest_dir="/tmp", filename="main.py")
        result = exec_in_pod(name, ["python", "/tmp/main.py"], timeout=timeout)
    finally:
        try:
            core_v1.delete_namespaced_pod(name, NAMESPACE)
        except Exception:
            log.warning("删除临时 Python Pod 失败：%s", name)

    result["pod_name"] = name
    result["node"] = node["name"]
    return result
