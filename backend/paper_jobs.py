"""Persistent Config -> Schedule -> Analyse workflows for the paper workspace."""
from __future__ import annotations

import json
import os
import re
import threading
import time

import yaml

from . import audit, db, k8s_client, paper_agents, task_events


def _run_in_thread(app, target, *args):
    def wrapped():
        with app.app_context():
            target(*args)

    thread = threading.Thread(target=wrapped, daemon=True)
    thread.start()


def _task_update(task_id, *, event_type=None, event_content=None, **changes):
    db.update_execution_task(task_id, **changes)
    if event_type:
        db.add_task_event(task_id, event_type, event_content or changes.get("detail", ""))
    task_events.publish_task(task_id)


def _advance(workspace_id, task_id, phase, content, progress, *, event_type="progress", data=None):
    db.update_paper_workspace(workspace_id, status="running", stage=phase)
    db.add_paper_workspace_event(workspace_id, phase, event_type, content, data=data)
    _task_update(
        task_id,
        status="running",
        progress=progress,
        detail=content,
        event_type=event_type,
        event_content=content,
    )


def _resource_rows(resource_spec):
    rows = []
    defaults = {
        "cloud": {"arch": "amd64", "image": "ubuntu:22.04"},
        "edge": {"arch": "arm64", "image": "ubuntu:22.04"},
        "device": {"arch": "arm64", "image": "ubuntu:22.04"},
    }
    for tier in ("cloud", "edge", "device"):
        source = resource_spec.get(tier) or {}
        count = min(5, max(0, int(source.get("count") or 0)))
        if not count:
            continue
        rows.append({
            "tier": tier,
            "count": count,
            "arch": source.get("arch") or defaults[tier]["arch"],
            "image": source.get("image") or defaults[tier]["image"],
            "cpu": source.get("cpu") or "500m",
            "memory": source.get("memory") or "512Mi",
            "gpu": min(4, max(0, int(source.get("gpu") or 0))),
        })
    return rows


def _first_mapping(source, keys):
    if not isinstance(source, dict):
        return None
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _merge_tier_resource(target, tier, source, evidence, filename):
    if not isinstance(source, dict):
        source = {"count": source} if isinstance(source, (int, float)) else {}
    current = target.setdefault(tier, {})
    aliases = {
        "count": ("count", "replicas", "instances", "number"),
        "arch": ("arch", "architecture", "kubernetes.io/arch"),
        "image": ("image", "container_image"),
        "cpu": ("cpu", "cpu_request"),
        "memory": ("memory", "mem", "memory_request"),
        "gpu": ("gpu", "gpus", "nvidia.com/gpu"),
    }
    for field, names in aliases.items():
        value = _first_mapping(source, names)
        if value not in (None, ""):
            current[field] = value
    current.setdefault("count", 1)
    evidence.append(f"{filename}：识别到 {tier} 资源定义")


def _walk_resource_documents(value, target, evidence, filename):
    if isinstance(value, list):
        for item in value:
            _walk_resource_documents(item, target, evidence, filename)
        return
    if not isinstance(value, dict):
        return
    tier_aliases = {"cloud": "cloud", "edge": "edge", "device": "device", "iot": "device"}
    explicit_tier = value.get("tier") or value.get("node_type") or value.get("type")
    if str(explicit_tier).lower() in tier_aliases:
        _merge_tier_resource(
            target, tier_aliases[str(explicit_tier).lower()], value, evidence, filename
        )
    for key, tier in tier_aliases.items():
        if key in value:
            _merge_tier_resource(target, tier, value[key], evidence, filename)

    kind = str(value.get("kind") or "").lower()
    spec = value.get("spec") if isinstance(value.get("spec"), dict) else {}
    template_spec = ((spec.get("template") or {}).get("spec") or {}) if isinstance(spec.get("template"), dict) else spec
    node_selector = template_spec.get("nodeSelector") or spec.get("nodeSelector") or {}
    if kind in {"pod", "deployment", "statefulset", "job", "daemonset"} or node_selector:
        tier = node_selector.get("node-type") or node_selector.get("smartkube/node-type") or "edge"
        tier = "device" if str(tier).lower() == "iot" else str(tier).lower()
        if tier not in {"cloud", "edge", "device"}:
            tier = "edge"
        containers = template_spec.get("containers") or []
        container = containers[0] if containers and isinstance(containers[0], dict) else {}
        requests = ((container.get("resources") or {}).get("requests") or {}) if isinstance(container, dict) else {}
        resource = {
            "count": spec.get("replicas") or 1,
            "arch": node_selector.get("kubernetes.io/arch"),
            "image": container.get("image"),
            "cpu": requests.get("cpu"),
            "memory": requests.get("memory"),
            "gpu": requests.get("nvidia.com/gpu"),
        }
        _merge_tier_resource(target, tier, resource, evidence, filename)

    for key, child in value.items():
        if key not in {"cloud", "edge", "device", "iot"}:
            _walk_resource_documents(child, target, evidence, filename)


def _infer_resources(workspace):
    resources = {}
    evidence = []
    combined_text = []
    files = db.list_paper_workspace_files_internal(workspace["id"], user_id=workspace["user_id"])
    for item in files:
        if not os.path.isfile(item["stored_path"]) or item["size"] > 1024 * 1024:
            continue
        try:
            with open(item["stored_path"], "rb") as handle:
                raw = handle.read(1024 * 1024)
            if b"\x00" in raw:
                continue
            text = raw.decode("utf-8", errors="replace")
        except OSError:
            continue
        combined_text.append(text)
        extension = os.path.splitext(item["original_name"])[1].lower()
        documents = []
        try:
            if extension == ".json":
                documents = [json.loads(text)]
            elif extension in {".yaml", ".yml"}:
                documents = list(yaml.safe_load_all(text))
        except (ValueError, yaml.YAMLError):
            evidence.append(f"{item['original_name']}：结构化解析失败，已回退文本提取")
        for document in documents:
            _walk_resource_documents(document, resources, evidence, item["original_name"])

    text = "\n".join(combined_text).lower()
    tier_patterns = {
        "cloud": r"\bcloud\b|云端|云节点|云侧",
        "edge": r"\bedge\b|边缘|边节点|边侧|jetson|orin",
        "device": r"\biot\b|\bdevice\b|端设备|物联网|stm32|esp32",
    }
    for tier, pattern in tier_patterns.items():
        if tier not in resources and re.search(pattern, text, re.I):
            resources[tier] = {"count": 1}
            evidence.append(f"文本语义：识别到 {tier} 层级")
    if not resources:
        resources["edge"] = {"count": 1}
        evidence.append("输入未声明资源层级：采用 1 个 edge Unit 作为最小可运行配套")

    detected_arch = None
    for canonical, pattern in (
        ("riscv64", r"risc[-_ ]?v(?:64)?"),
        ("arm64", r"\b(?:arm64|aarch64)\b"),
        ("amd64", r"\b(?:amd64|x86_64|x86-64)\b"),
    ):
        if re.search(pattern, text, re.I):
            detected_arch = canonical
            break
    image_match = re.search(r"(?:image|镜像)\s*[:=]\s*[\"']?([a-z0-9._/-]+(?::[a-z0-9._-]+)?)", text, re.I)
    defaults = {
        "cloud": {"arch": "amd64", "image": "ubuntu:22.04"},
        "edge": {"arch": "arm64", "image": "ubuntu:22.04"},
        "device": {"arch": "arm64", "image": "ubuntu:22.04"},
    }
    normalized = {}
    for tier, source in resources.items():
        count = min(5, max(1, int(source.get("count") or 1)))
        normalized[tier] = {
            "count": count,
            "arch": str(source.get("arch") or (detected_arch if len(resources) == 1 else None) or defaults[tier]["arch"]),
            "image": str(source.get("image") or (image_match.group(1) if image_match else defaults[tier]["image"])),
            "cpu": str(source.get("cpu") or "500m"),
            "memory": str(source.get("memory") or "512Mi"),
            "gpu": min(4, max(0, int(source.get("gpu") or 0))),
        }
    while sum(item["count"] for item in normalized.values()) > 8:
        tier = max(normalized, key=lambda key: normalized[key]["count"])
        normalized[tier]["count"] -= 1
    return normalized, evidence


def _build_configuration(workspace, documents, intelligence):
    resource_spec, evidence = _infer_resources(workspace)
    generated = paper_agents.run_config_agent(
        documents,
        intelligence,
        {"resources": _resource_rows(resource_spec), "evidence": evidence},
        workspace["mode"],
    )
    return {
        "schema_version": "smart-kube.workspace/v1",
        "experiment": {
            "id": workspace["experiment_id"],
            "name": workspace["experiment_name"],
            "goal": workspace["goal"],
            "mode": workspace["mode"],
        },
        "inputs": [
            {"name": item["original_name"], "size": item["size"], "content_type": item["content_type"]}
            for item in workspace.get("files", [])
        ],
        "document_intelligence": intelligence,
        "resources": generated["resources"],
        "workflow_steps": generated["workflow_steps"],
        "analysis_plan": generated["analysis_plan"],
        "assumptions": generated["assumptions"],
        "resource_inference": {
            "source": "llm_with_rule_evidence",
            "evidence": evidence,
            "rule_candidates": _resource_rows(resource_spec),
        },
        "agent_trace": [intelligence["agent_trace"], generated["agent_trace"]],
        "lifecycle": {"reclaim": "manual", "retain_after_completion": True},
    }


def _schedule(user, experiment_id, configuration, workspace_id, task_id):
    requested = sum(row["count"] for row in configuration["resources"])
    created = []
    completed = 0
    for row in configuration["resources"]:
        for index in range(row["count"]):
            completed += 1
            detail = f"正在调度 {row['tier']} 资源 {index + 1}/{row['count']}"
            progress = 35 + round(35 * completed / max(1, requested))
            _advance(workspace_id, task_id, "schedule", detail, progress)
            placement = k8s_client.create_ssh_pod(
                user,
                arch=row["arch"],
                image=row["image"],
                cpu=row["cpu"],
                memory=row["memory"],
                node_type=row["tier"],
                experiment_id=experiment_id,
                gpu=row["gpu"],
            )
            created.append(placement)
            partial_schedule = {
                "strategy": "existing-smart-kube-placement",
                "requested": requested,
                "created": len(created),
                "placements": created,
                "resources_retained": True,
            }
            db.update_paper_workspace(workspace_id, schedule_json=partial_schedule)
            db.add_paper_workspace_event(
                workspace_id,
                "schedule",
                "placement",
                f"{placement['pod_name']} 已落位到 {placement['node']}",
                data={
                    "pod_name": placement["pod_name"],
                    "node": placement["node"],
                    "tier": placement["node_type"],
                    "arch": placement["arch"],
                },
            )
    return {
        "strategy": "existing-smart-kube-placement",
        "requested": requested,
        "created": len(created),
        "placements": created,
        "resources_retained": True,
    }


def _analysis_telemetry(workspace):
    events = workspace.get("events") or []
    phase_bounds = {}
    for event in events:
        phase = event.get("phase")
        if phase not in {"config", "schedule", "analysis", "report"}:
            continue
        bounds = phase_bounds.setdefault(phase, [event["created_at"], event["created_at"]])
        bounds[0] = min(bounds[0], event["created_at"])
        bounds[1] = max(bounds[1], event["created_at"])
    durations = [
        {"phase": phase, "seconds": max(1, bounds[1] - bounds[0] + 1)}
        for phase, bounds in phase_bounds.items()
    ]
    return {
        "stage_durations": durations,
        "resource_distribution": [
            {
                "tier": tier,
                "count": sum(
                    1 for item in (workspace.get("schedule_json") or {}).get("placements", [])
                    if item.get("node_type") == tier
                ),
            }
            for tier in ("cloud", "edge", "device")
        ],
    }


def start_workspace_job(app, workspace, user, source_ip):
    task = db.create_execution_task(
        user["id"],
        workspace["experiment_id"],
        "paper",
        workspace["name"],
        "等待文档理解 Agent 读取正文",
        {"workspace_id": workspace["id"], "mode": workspace["mode"]},
    )
    task_events.publish_task(task["id"])
    _run_in_thread(app, _execute_workspace, workspace["id"], task["id"], user, source_ip)
    return task


def _execute_workspace(workspace_id, task_id, user, source_ip):
    _task_update(task_id, started_at=int(time.time()))
    try:
        _advance(workspace_id, task_id, "intake", "文档理解 Agent 正在提取并阅读文件正文", 6, event_type="agent_started")
        workspace = db.get_paper_workspace(workspace_id, user_id=user["id"])
        internal_files = db.list_paper_workspace_files_internal(workspace_id, user_id=user["id"])
        documents = paper_agents.extract_documents(internal_files)
        extraction = [{
            "name": item["name"],
            "characters": len(item["text"]),
            "truncated": item["truncated"],
            "issue": item["extraction_issue"],
        } for item in documents]
        db.add_paper_workspace_event(
            workspace_id, "intake", "extracted", "文件正文提取完成", data={"files": extraction}
        )
        intelligence = paper_agents.run_intent_agent(documents)
        db.update_paper_workspace(
            workspace_id, name=intelligence["title"], goal=intelligence["goal"]
        )
        db.update_experiment(
            workspace["experiment_id"],
            intelligence["title"],
            f"论文工作区：{intelligence['summary'][:1000]}",
        )
        _task_update(task_id, title=intelligence["title"])
        db.add_paper_workspace_event(
            workspace_id,
            "intake",
            "agent_completed",
            f"文档理解 Agent 已生成实验元信息：{intelligence['title']}",
            data={key: value for key, value in intelligence.items() if key != "agent_trace"},
        )

        _advance(workspace_id, task_id, "config", "配置 Agent 正在根据正文与解析证据形成配置", 20, event_type="agent_started")
        workspace = db.get_paper_workspace(workspace_id, user_id=user["id"])
        configuration = _build_configuration(workspace, documents, intelligence)
        if not configuration["resources"]:
            raise ValueError("至少需要一项云、边或端资源")
        inferred_spec = {row["tier"]: {key: value for key, value in row.items() if key != "tier"} for row in configuration["resources"]}
        db.update_paper_workspace(workspace_id, config_json=configuration, resource_spec=inferred_spec)
        for evidence in configuration["resource_inference"]["evidence"]:
            db.add_paper_workspace_event(workspace_id, "config", "inference", evidence)
        _advance(
            workspace_id, task_id, "config", "配置 Agent 已生成配置并通过结构校验", 30,
            event_type="agent_completed", data=configuration,
        )

        _advance(workspace_id, task_id, "schedule", "正在读取现有集群能力并生成落位", 35)
        schedule = _schedule(user, workspace["experiment_id"], configuration, workspace_id, task_id)
        db.update_paper_workspace(workspace_id, schedule_json=schedule)
        _advance(workspace_id, task_id, "schedule", "资源调度完成，已保留运行实例", 72, data=schedule)

        workspace = db.get_paper_workspace(workspace_id, user_id=user["id"])
        if workspace["mode"] == "full":
            _advance(workspace_id, task_id, "analysis", "分析 Agent 正在核验配置、落位和过程证据", 82, event_type="agent_started")
            analysis = paper_agents.run_analysis_agent(
                workspace.get("config_json") or {},
                workspace.get("schedule_json") or {},
                workspace.get("events") or [],
                retry=int(workspace.get("retries") or 0),
            )
            analysis.update(_analysis_telemetry(workspace))
            db.update_paper_workspace(workspace_id, analysis_json=analysis)
            _advance(
                workspace_id, task_id, "analysis",
                f"分析 Agent 完成，结论：{analysis['verdict']}", 94,
                event_type="agent_completed", data=analysis,
            )
        else:
            db.add_paper_workspace_event(workspace_id, "analysis", "skipped", "按用户选择跳过完整分析")

        workspace = db.get_paper_workspace(workspace_id, user_id=user["id"])
        _advance(workspace_id, task_id, "report", "报告 Agent 正在根据真实过程证据撰写报告", 97, event_type="agent_started")
        report, report_trace = paper_agents.run_report_agent(workspace)
        configuration = workspace.get("config_json") or {}
        configuration.setdefault("agent_trace", []).append(report_trace)
        db.update_paper_workspace(workspace_id, config_json=configuration)
        db.add_paper_workspace_event(
            workspace_id, "report", "agent_completed", "报告 Agent 已生成 Markdown 实验报告",
            data={"agent_trace": report_trace},
        )
        now = int(time.time())
        db.update_paper_workspace(
            workspace_id,
            status="completed",
            stage="completed",
            report_md=report,
            finished_at=now,
        )
        db.add_paper_workspace_event(workspace_id, "completed", "succeeded", "流程完成，资源保持运行")
        _task_update(
            task_id,
            status="succeeded",
            progress=100,
            detail="流程完成，等待用户决定是否回收资源",
            result=report,
            finished_at=now,
            event_type="succeeded",
            event_content="工作区流程完成",
        )
        audit.log(
            user["id"],
            user["username"],
            "paper_workspace_complete",
            json.dumps({"workspace_id": workspace_id, "experiment_id": workspace["experiment_id"]}),
            source_ip=source_ip,
        )
    except Exception as exc:
        message = str(exc)[:4000]
        now = int(time.time())
        current = db.get_paper_workspace(workspace_id, user_id=user["id"])
        stage = current["stage"] if current else "unknown"
        created = int(((current or {}).get("schedule_json") or {}).get("created") or 0)
        failure_detail = (
            f"工作流执行失败，已创建的 {created} 个资源保持不变"
            if created else "工作流执行失败，未创建新资源"
        )
        db.update_paper_workspace(workspace_id, status="failed", finished_at=now)
        db.add_paper_workspace_event(workspace_id, stage, "failed", message)
        _task_update(
            task_id,
            status="failed",
            detail=failure_detail,
            error=message,
            finished_at=now,
            event_type="failed",
            event_content=message,
        )


def start_analysis_retry(app, workspace, user, source_ip):
    db.update_paper_workspace(
        workspace["id"], status="running", stage="analysis", finished_at=None
    )
    task = db.create_execution_task(
        user["id"],
        workspace["experiment_id"],
        "paper_analysis",
        f"重新分析 {workspace['name']}",
        "等待重新分析",
        {"workspace_id": workspace["id"], "retry": workspace.get("retries", 0) + 1},
    )
    task_events.publish_task(task["id"])
    _run_in_thread(app, _execute_analysis_retry, workspace["id"], task["id"], user, source_ip)
    return task


def _execute_analysis_retry(workspace_id, task_id, user, source_ip):
    now = int(time.time())
    _task_update(task_id, status="running", started_at=now)
    try:
        workspace = db.get_paper_workspace(workspace_id, user_id=user["id"])
        retry_number = int(workspace.get("retries") or 0) + 1
        db.update_paper_workspace(
            workspace_id,
            status="running",
            stage="analysis",
            retries=retry_number,
            finished_at=None,
        )
        _advance(
            workspace_id, task_id, "analysis",
            f"分析 Agent 开始第 {retry_number} 次分析", 30, event_type="agent_started",
        )
        workspace = db.get_paper_workspace(workspace_id, user_id=user["id"])
        analysis = paper_agents.run_analysis_agent(
            workspace.get("config_json") or {},
            workspace.get("schedule_json") or {},
            workspace.get("events") or [],
            retry=retry_number,
        )
        analysis.update(_analysis_telemetry(workspace))
        db.update_paper_workspace(workspace_id, analysis_json=analysis)
        _advance(
            workspace_id, task_id, "analysis",
            f"分析 Agent 重新分析完成，结论：{analysis['verdict']}", 85,
            event_type="agent_completed", data=analysis,
        )
        workspace = db.get_paper_workspace(workspace_id, user_id=user["id"])
        _advance(workspace_id, task_id, "report", "报告 Agent 正在根据重试结果更新报告", 92, event_type="agent_started")
        report, report_trace = paper_agents.run_report_agent(workspace)
        configuration = workspace.get("config_json") or {}
        configuration.setdefault("agent_trace", []).append(report_trace)
        finished = int(time.time())
        db.update_paper_workspace(
            workspace_id,
            status="completed",
            stage="completed",
            config_json=configuration,
            report_md=report,
            finished_at=finished,
        )
        db.add_paper_workspace_event(
            workspace_id, "report", "agent_completed", "报告 Agent 已更新 Markdown 实验报告",
            data={"agent_trace": report_trace},
        )
        db.add_paper_workspace_event(workspace_id, "completed", "succeeded", f"第 {retry_number} 次分析完成")
        _task_update(
            task_id,
            status="succeeded",
            progress=100,
            detail="重新分析完成",
            result=report,
            finished_at=finished,
            event_type="succeeded",
            event_content="重新分析完成",
        )
        audit.log(
            user["id"], user["username"], "paper_analysis_retry",
            json.dumps({"workspace_id": workspace_id, "retry": retry_number}), source_ip=source_ip,
        )
    except Exception as exc:
        message = str(exc)[:4000]
        finished = int(time.time())
        db.update_paper_workspace(workspace_id, status="failed", finished_at=finished)
        db.add_paper_workspace_event(workspace_id, "analysis", "failed", message)
        _task_update(
            task_id,
            status="failed",
            detail="重新分析失败",
            error=message,
            finished_at=finished,
            event_type="failed",
            event_content=message,
        )
