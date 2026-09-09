"""Deterministic placement checks against a current Kubernetes snapshot."""
from __future__ import annotations

import copy
from decimal import Decimal

from kubernetes.utils.quantity import parse_quantity

GPU = "nvidia.com/gpu"
RESOURCES = ("cpu", "memory", GPU, "pods", "ephemeral-storage")
PULL_ERRORS = {"ErrImagePull", "ImagePullBackOff", "InvalidImageName"}


def quantity(value):
    try:
        result = parse_quantity(str(value or "0"))
        if not result.is_finite() or result < 0:
            raise ValueError()
        return result
    except Exception as exc:
        raise ValueError(f"Invalid Kubernetes resource quantity: {value}") from exc


def pod_requests(pod):
    """Include init peaks, restartable init sidecars and Pod overhead."""
    spec = pod.get("spec") or {}
    keys = set(RESOURCES) | set(spec.get("overhead") or {})
    for container in (spec.get("containers") or []) + (spec.get("initContainers") or []):
        resources = container.get("resources") or {}
        keys.update(resources.get("requests") or {})
        keys.update(resources.get("limits") or {})
    total = {key: Decimal(0) for key in keys}
    peak = total.copy()
    sidecars = total.copy()

    def requests(container):
        resources = container.get("resources") or {}
        req, limits = resources.get("requests") or {}, resources.get("limits") or {}
        return {key: quantity(req.get(key, limits.get(key, 0))) for key in keys}

    for container in spec.get("containers") or []:
        for key, value in requests(container).items():
            total[key] += value
    for container in spec.get("initContainers") or []:
        values = requests(container)
        for key in keys:
            if container.get("restartPolicy") == "Always":
                sidecars[key] += values[key]
                peak[key] = max(peak[key], sidecars[key])
            else:
                peak[key] = max(peak[key], sidecars[key] + values[key])
    pod_level = (spec.get("resources") or {}).get("requests") or {}
    for key in keys:
        total[key] = max(total[key] + sidecars[key], peak[key])
        total[key] = max(total[key], quantity(pod_level.get(key, 0)))
        total[key] += quantity((spec.get("overhead") or {}).get(key, 0))
    total["pods"] = Decimal(1)
    return total


def image_name(image):
    image = image.removeprefix("docker.io/").removeprefix("index.docker.io/")
    if "/" not in image:
        image = "library/" + image
    if ":" not in image.rsplit("/", 1)[-1] and "@" not in image:
        image += ":latest"
    return image


def snapshot(nodes, pods, quotas, limits, namespace):
    nodes = copy.deepcopy(nodes)
    by_name = {node["name"]: node for node in nodes}
    for node in nodes:
        allocatable = node.get("allocatable") or {}
        node["available"] = {key: str(quantity(allocatable.get(key, 0))) for key in set(RESOURCES) | set(allocatable)}
        node["image_failures"] = {}
    for pod in pods:
        if (pod.get("status") or {}).get("phase") in {"Succeeded", "Failed"}:
            continue
        metadata, spec, status = pod.get("metadata") or {}, pod.get("spec") or {}, pod.get("status") or {}
        node_name = spec.get("nodeName") or (metadata.get("annotations") or {}).get("smartkube/selected-node")
        node = by_name.get(node_name)
        if not node:
            continue
        for key, value in pod_requests(pod).items():
            node["available"][key] = str(max(Decimal(0), quantity(node["available"].get(key, 0)) - value))
        for container in (status.get("containerStatuses") or []) + (status.get("initContainerStatuses") or []):
            waiting = (container.get("state") or {}).get("waiting") or {}
            if waiting.get("reason") in PULL_ERRORS and not metadata.get("deletionTimestamp"):
                node["image_failures"][image_name(container["image"])] = waiting.get("message") or waiting["reason"]
    return {"nodes": nodes, "quotas": quotas, "limit_ranges": limits, "namespace": namespace}


def requirements(cpu, memory, gpu=0, cpu_limit=None, memory_limit=None):
    if isinstance(gpu, bool) or quantity(gpu) != int(quantity(gpu)):
        raise ValueError("GPU request must be a non-negative integer")
    req = {"cpu": str(cpu), "memory": str(memory), GPU: str(gpu), "pods": "1"}
    lim = {"cpu": str(cpu_limit or cpu), "memory": str(memory_limit or memory), GPU: str(gpu)}
    for key in lim:
        if quantity(req[key]) > quantity(lim[key]):
            raise ValueError(f"Resource request exceeds limit: {key}")
    if quantity(cpu) <= 0 or quantity(memory) <= 0:
        raise ValueError("CPU and memory requests must be positive")
    if not quantity(gpu):
        req.pop(GPU)
        lim.pop(GPU)
    return req, lim


def quota_applies(quota):
    # These Pods have resource requests, no deadline/priority and no inter-Pod affinity.
    values = {"NotBestEffort": "", "NotTerminating": ""}
    spec = quota.get("spec") or {}
    selectors = [{"scopeName": name, "operator": "Exists"} for name in spec.get("scopes") or []]
    selectors += (spec.get("scopeSelector") or {}).get("matchExpressions") or []
    for selector in selectors:
        name, operator = selector["scopeName"], selector["operator"]
        if name not in {"BestEffort", "NotBestEffort", "Terminating", "NotTerminating", "PriorityClass", "CrossNamespacePodAffinity"}:
            raise RuntimeError(f"Unsupported ResourceQuota scope: {name}")
        present = name in values
        options = selector.get("values") or []
        matches = {"Exists": present, "DoesNotExist": not present,
                   "In": present and values.get(name) in options,
                   "NotIn": not present or values.get(name) not in options}
        if operator not in matches:
            raise RuntimeError(f"Unsupported ResourceQuota scope operator: {operator}")
        if not matches[operator]:
            return False
    return True


def node_rejections(node, req, image):
    reasons = []
    if node.get("ready") != "True":
        reasons.append("NotReady")
    if node.get("unschedulable"):
        reasons.append("SchedulingDisabled")
    if node.get("os", "linux") != "linux":
        reasons.append("requires Linux")
    for condition in node.get("conditions", []):
        if condition["type"] in {"MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable"} and condition["status"] == "True":
            reasons.append(condition["type"])
    for taint in node.get("taints", []):
        if taint.get("effect") in {"NoSchedule", "NoExecute"}:
            reasons.append("untolerated taint: " + taint["key"])
    for key, value in req.items():
        available = node.get("available", {}).get(key, "0")
        if quantity(value) > quantity(available):
            reasons.append(f"insufficient {key}: requested {value}, available {available}")
    normalized = image_name(image) if image else ""
    cached = {image_name(name) for name in node.get("images", [])}
    if normalized in node.get("image_failures", {}):
        reasons.append("image pull failed: " + node["image_failures"][normalized])
    if normalized and normalized not in cached:
        # A node-side proxy/DNS failure affects uncached images from the same registry.
        for failed_image, message in node.get("image_failures", {}).items():
            if registry(failed_image) == registry(normalized) and any(
                token in message.lower() for token in ("proxyconnect", "connection refused", "no such host", "network is unreachable")
            ):
                reasons.append("image registry unreachable on node: " + message)
                break
    arch = node.get("arch")
    if normalized.startswith(("library/python:", "library/ubuntu:")) and arch not in {"amd64", "arm64"} and normalized not in cached:
        reasons.append(f"image platform unverified for {arch}; provide a compatible image")
    if normalized.startswith("nvidia/cuda:"):
        if quantity(req.get(GPU, 0)) == 0:
            reasons.append("CUDA image requires an explicit GPU request")
        if arch != "amd64":
            reasons.append("generic CUDA image is not a validated Jetson/ARM runtime; provide a compatible GPU image")
    return reasons


def registry(image):
    first = image.split("/", 1)[0]
    return first if "." in first or ":" in first or first == "localhost" else "docker.io"


def check_namespace(state, req, lim, services=0):
    for limit in state.get("limit_ranges", []):
        for item in limit.get("spec", {}).get("limits", []):
            if item.get("type") == "Container":
                for key, value in (item.get("default") or {}).items():
                    lim.setdefault(key, value)
                for key, value in (item.get("defaultRequest") or {}).items():
                    req.setdefault(key, value)
    for key, value in lim.items():
        req.setdefault(key, value)
    for limit in state.get("limit_ranges", []):
        for item in limit.get("spec", {}).get("limits", []):
            if item.get("type") not in {"Container", "Pod"}:
                continue
            for key in set(req) | set(lim):
                minimum = (item.get("min") or {}).get(key)
                maximum = (item.get("max") or {}).get(key)
                ratio = (item.get("maxLimitRequestRatio") or {}).get(key)
                if minimum and quantity(req.get(key, 0)) < quantity(minimum):
                    raise RuntimeError(f"LimitRange: {key} request below minimum {minimum}")
                if maximum and quantity(lim.get(key, req.get(key, 0))) > quantity(maximum):
                    raise RuntimeError(f"LimitRange: {key} limit exceeds maximum {maximum}")
                if ratio and quantity(lim.get(key, 0)) > quantity(req.get(key, 0)) * quantity(ratio):
                    raise RuntimeError(f"LimitRange: {key} limit/request ratio exceeds {ratio}")
    additions = {"pods": 1, "count/pods": 1, "services": services, "count/services": services, "services.nodeports": services}
    for key in (set(req) | set(lim)) - {"pods"}:
        additions["requests." + key] = req.get(key, 0)
        additions["limits." + key] = lim.get(key, 0)
        additions[key] = req.get(key, 0)
    for quota in state.get("quotas", []):
        if not quota_applies(quota):
            continue
        status = quota.get("status") or {}
        hard = status.get("hard") or quota.get("spec", {}).get("hard") or {}
        used = status.get("used") or {}
        for key, amount in additions.items():
            if key in hard and quantity(used.get(key, 0)) + quantity(amount) > quantity(hard[key]):
                raise RuntimeError(f"ResourceQuota {quota['metadata']['name']}: {key} insufficient (used {used.get(key, 0)}, requested {amount}, hard {hard[key]})")
    return additions


def select(state, req, lim, image, arch=None, hostname=None, node_type=None, fallback=False, reserve=False, services=0):
    additions = check_namespace(state, req, lim, services)
    rejected = {}
    candidates = []
    for node in state["nodes"]:
        reasons = node_rejections(node, req, image)
        if hostname and hostname not in {node["name"], node.get("hostname")}:
            reasons.append("hostname mismatch")
        if arch and node["arch"] != arch:
            reasons.append("architecture mismatch")
        if node_type and node.get("node_type") != node_type and not fallback:
            reasons.append("node type mismatch")
        if reasons:
            rejected[node["name"]] = reasons
        else:
            candidates.append(node)
    if not candidates:
        details = "; ".join(f"{name}: {', '.join(reasons)}" for name, reasons in rejected.items())
        raise RuntimeError("集群资源预检失败：" + (details or "集群没有节点"))
    candidates.sort(key=lambda n: (
        n.get("node_type") != node_type if node_type else False,
        image_name(image) not in {image_name(name) for name in n.get("images", [])} if image else False,
        -quantity(n["available"].get("memory", 0)), n["name"],
    ))
    node = candidates[0]
    result = copy.deepcopy(node)
    if reserve:
        for key, value in req.items():
            node["available"][key] = str(quantity(node["available"].get(key, 0)) - quantity(value))
        for quota in state.get("quotas", []):
            if not quota_applies(quota):
                continue
            used = quota.setdefault("status", {}).setdefault("used", {})
            for key, value in additions.items():
                used[key] = str(quantity(used.get(key, 0)) + quantity(value))
    return result, rejected
