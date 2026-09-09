"""Bounded multi-experiment orchestration with a reusable, preallocated resource pool."""
from copy import deepcopy
import time

from . import db, k8s_client, paper_agents
from .scheduling import quantity


def peak_pool(configurations):
    """Take per-compatible-slot maxima, not sums across sequential experiments."""
    pools, assignments = {}, []
    for configuration in configurations:
        indexes, assignment = {}, []
        for resource in configuration["resources"]:
            key = (resource["tier"], resource["arch"], resource["image"])
            group = pools.setdefault(key, [])
            for _ in range(resource["count"]):
                index = indexes.get(key, 0)
                indexes[key] = index + 1
                assignment.append((key, index))
                if index == len(group):
                    group.append({**resource, "count": 1})
                else:
                    for field in ("cpu", "memory", "gpu"):
                        if quantity(resource[field]) > quantity(group[index][field]):
                            group[index][field] = resource[field]
        assignments.append(assignment)
    rows, lookup = [], {}
    for key, group in pools.items():
        for index, row in enumerate(group):
            lookup[(key, index)] = len(rows)
            rows.append(row)
    if len(rows) > 8:
        raise ValueError("三个实验的兼容资源峰值超过 8 个 Units，未创建资源；请缩小实验范围")
    return rows, [[lookup[slot] for slot in assignment] for assignment in assignments]


def evidence_reports(workspace):
    """Always leave usable reports, including when the model or a run fails."""
    config = workspace.get("config_json") or {}
    cases = config.get("suite") or []
    schedule = workspace.get("schedule_json") or {}
    process = ["# 过程报告", "", f"工作：{workspace['name']}",
               f"资源回收：{'已回收' if workspace.get('resources_reclaimed') else '尚未回收'}", ""]
    comparison = ["# 实验对比报告", "", "以下依据论文解析记录和真实执行证据。缺失或不同口径指标不进行数值比较。", ""]
    outcomes = {item["id"]: item for item in schedule.get("suite", [])}
    for case in cases:
        result = outcomes.get(case["id"], {})
        status = result.get("status", "未执行")
        process += [f"## {case['title']}", f"状态：{status}", case.get("error", result.get("error", "")), ""]
        comparison += [f"## {case['title']}", f"目标：{case.get('goal', '')}", "### 论文结果与依据",
                       *[f"- {finding}" for finding in case.get("paper_findings", [])],
                       case.get("source_quote") or "未提取到可引用的结果。", "### 本次运行", f"状态：{status}"]
        for run in result.get("executions", []):
            process += [f"### {run.get('pod_name')} / {run.get('run_id')}",
                        f"状态 {run.get('status')}，退出码 {run.get('exit_code')}，运行耗时 {run.get('duration_seconds')} 秒",
                        "```text", str(run.get("stdout") or run.get("stderr") or "无输出")[:16000].replace("```", "'''"), "```"]
            comparison += [f"- {run.get('node')}：{run.get('status')}；程序观测：{str(run.get('observation') or '未取得结构化结果')[:4000]}"]
        analysis = result.get("analysis") or {}
        comparison += ["### 对比结论", analysis.get("summary") or "证据不足，不可比较，不能声称复现成功。",
                       *[f"- {risk}" for risk in analysis.get("risks", [])], ""]
    process += ["## Agent 调用与事件"]
    process += [f"- {event['phase']} / {event['event_type']}：{event['content']}" for event in workspace.get("events", [])]
    comparison += ["## 未覆盖实验", *[f"- {text}" for text in config.get("document_intelligence", {}).get("omitted_experiments", [])]]
    return "\n\n".join(process), "\n\n".join(comparison)


def reanalyse_suite(workspace, retry):
    schedule = workspace.get("schedule_json") or {}
    analyses = []
    for case in (workspace.get("config_json") or {}).get("suite", []):
        result = next((item for item in schedule.get("suite", []) if item["id"] == case["id"]), None)
        if not result or not result.get("executions"):
            continue
        result["analysis"] = paper_agents.run_analysis_agent(case["configuration"],
            {"placements": schedule.get("placements", []), "executions": result["executions"]}, workspace.get("events", []), retry=retry)
        analyses.append(result["analysis"])
        db.add_paper_workspace_event(workspace["id"], "analysis", "agent_returned", f"对比分析重试完成：{case['title']}",
                                    data={"from": "analysis", "to": "orchestrator", "case_id": case["id"]})
    db.update_paper_workspace(workspace["id"], schedule_json=schedule)
    previous = workspace.get("analysis_json") or {}
    return {**previous, "verdict": "passed" if len(analyses) == len((workspace.get("config_json") or {}).get("suite", [])) and analyses and all(a["verdict"] == "passed" for a in analyses) else "needs_attention",
            "summary": f"已重新核验 {len(analyses)} 个实验的现存执行证据；没有重新运行实验。",
            "checks": [check for item in analyses for check in item.get("checks", [])],
            "risks": [risk for item in analyses for risk in item.get("risks", [])]}


def execute_suite(workspace_id, task_id, user, documents, intelligence, internal_files):
    from . import paper_jobs as jobs
    workspace = db.get_paper_workspace(workspace_id)
    cases = [{**item, "status": "pending"} for item in intelligence["experiments"]]
    configuration = {"schema_version": "testbed.suite/v2", "document_intelligence": intelligence,
                     "experiment": {"id": workspace["experiment_id"], "mode": workspace["mode"]},
                     "suite": cases, "resources": [], "agent_trace": [intelligence["agent_trace"]],
                     "lifecycle": {"reclaim": "automatic_on_failure", "execution": "sequential", "max_experiments": 3}}
    schedule = {"suite": [], "placements": [], "created": 0, "executions": []}
    failure = None

    def call(stage, case, action="agent_called"):
        db.add_paper_workspace_event(workspace_id, stage, action,
                                    f"编排 Agent {'委派' if action == 'agent_called' else '收到'} {stage}：{case['title']}",
                                    data={"from": "orchestrator" if action == "agent_called" else stage,
                                          "to": stage if action == "agent_called" else "orchestrator", "case_id": case["id"]})

    def save():
        schedule["executions"] = [{**run, "case_id": result["id"], "experiment_title": result["title"]}
                                  for result in schedule["suite"] for run in result.get("executions", [])]
        expected = sum(sum(row["count"] for row in case.get("configuration", {}).get("resources", [])) for case in cases) if workspace["mode"] == "full" else 0
        schedule["execution_summary"] = {"total": expected, "completed": len(schedule["executions"]),
                                         "failed": sum(run["status"] != "succeeded" for run in schedule["executions"]),
                                         "succeeded": sum(run["status"] == "succeeded" for run in schedule["executions"])}
        db.update_paper_workspace(workspace_id, config_json=configuration, schedule_json=schedule)

    try:
        jobs._advance(workspace_id, task_id, "config", f"编排 Agent 已识别 {len(cases)} 个实验，逐项规划峰值资源", 15)
        db.update_paper_workspace(workspace_id, config_json=configuration)
        for case in cases:
            case["status"] = "planning"
            call("config", case)
            case_intelligence = {**intelligence, **deepcopy(case), "experiments": [deepcopy(case)]}
            case_workspace = {**workspace, "goal": case["goal"], "experiment_name": case["title"]}
            case["configuration"] = jobs._plan_configuration(case_workspace, documents, case_intelligence)
            case["status"] = "planned"
            call("config", case, "agent_returned")
            save()
        rows, bindings = peak_pool([case["configuration"] for case in cases])
        configuration["resources"] = rows
        configuration["pool_bindings"] = bindings
        configuration["preflight"] = k8s_client.preflight_resources(rows, allow_constraint_fallback=True)
        save()
        call("schedule", {"id": "pool", "title": "全部实验的峰值资源池"})
        schedule.update(jobs._schedule(user, workspace["experiment_id"], configuration, workspace_id, task_id))
        save()
        # Pod creation alone is not readiness. No code generation until the entire pool is ready.
        for placement in schedule["placements"]:
            jobs._wait_for_pod_ready(placement["pod_name"])
        call("schedule", {"id": "pool", "title": "全部资源已就绪"}, "agent_returned")
        for index, case in enumerate(cases):
            case_config = case["configuration"]
            result = {"id": case["id"], "title": case["title"], "status": "running", "executions": []}
            schedule["suite"].append(result)
            case["status"] = "running"
            save()
            if workspace["mode"] != "full":
                case["status"] = result["status"] = "scheduled"
                continue
            jobs._advance(workspace_id, task_id, "code", f"实验 {index + 1}/{len(cases)}：{case['title']}", 72, event_type="agent_started")
            call("code", case)
            intent = {key: value for key, value in case.items() if key not in {"configuration", "status"}}
            program = paper_agents.run_code_agent(documents, {**intelligence, **intent, "experiments": [intent]}, case_config)
            program = deepcopy(program)
            program["runtime"]["filename"] = f"experiment_{index + 1}.py"
            jobs._align_configuration_runtime(case_config, program)
            artifact = jobs._persist_generated_program(workspace_id, user["id"], internal_files, program)
            configuration["generated_program"] = program
            call("code", case, "agent_returned")
            targets = [row["tier"] for row in case_config["resources"] for _ in range(row["count"])]
            tier_indexes, selected = {}, []
            for tier, pool_index in zip(targets, bindings[index]):
                tier_indexes[tier] = tier_indexes.get(tier, 0) + 1
                selected.append({**schedule["placements"][pool_index], "node_type": tier, "tier_index": tier_indexes[tier]})
            case_schedule = {"placements": selected, "created": len(selected), "requested": len(selected)}
            result["placements"] = selected

            def persist(value):
                result.update(executions=deepcopy(value.get("executions", [])))
                save()

            call("execute", case)
            case_schedule = jobs._execute_generated_program(workspace_id, task_id, case_schedule, program,
                                                            artifact["stored_path"], persist=persist)
            call("execute", case, "agent_returned")
            jobs._advance(workspace_id, task_id, "analysis", f"对比分析实验 {index + 1} 的论文结论与运行结果", 89, event_type="agent_started")
            call("analysis", case)
            result["analysis"] = paper_agents.run_analysis_agent(case_config, case_schedule, db.get_paper_workspace(workspace_id)["events"])
            case["status"] = result["status"] = "completed" if result["analysis"]["verdict"] != "failed" else "failed"
            save()
            call("analysis", case, "agent_returned")
            if result["status"] == "failed":
                raise RuntimeError(f"实验 {index + 1} 未通过证据分析，停止后续执行")
        save()
    except Exception as exc:
        failure = exc
        # _schedule persists partial allocation, which must survive a later placement failure.
        current = db.get_paper_workspace(workspace_id)
        partial = current.get("schedule_json") or {}
        if partial.get("created", 0) > schedule.get("created", 0):
            schedule.update(partial)
            schedule.setdefault("suite", [])
        if partial.get("cleanup"):
            schedule.update(cleanup=partial["cleanup"], resources_retained=partial.get("resources_retained", False))
        for case in cases:
            if case["status"] in {"running", "planning"}:
                case.update(status="failed", error=str(exc)[:2000])
            elif case["status"] in {"pending", "planned"}:
                case["status"] = "skipped"
        for result in schedule["suite"]:
            if result["status"] == "running":
                result.update(status="failed", error=str(exc)[:2000])
        save()
        jobs.reclaim_failed_workspace(workspace_id)

    analyses = [result["analysis"] for result in schedule["suite"] if result.get("analysis")]
    analysis = {"verdict": "failed" if failure else "needs_attention" if not analyses or any(a["verdict"] != "passed" for a in analyses) else "passed",
                "summary": f"已完成 {sum(case['status'] == 'completed' for case in cases)}/{len(cases)} 个实验，分别核验论文结论与运行证据。",
                "checks": [check for item in analyses for check in item.get("checks", [])],
                "risks": [risk for item in analyses for risk in item.get("risks", [])],
                "recommendations": [], "suite": [{"id": case["id"], "title": case["title"], "status": case["status"]} for case in cases]}
    db.update_paper_workspace(workspace_id, analysis_json=analysis)
    current = db.get_paper_workspace(workspace_id)
    process, comparison = evidence_reports(current)
    db.update_paper_workspace(workspace_id, report_md=process, comparison_report_md=comparison)
    if not failure:
        try:
            jobs._advance(workspace_id, task_id, "report", "过程报告 Agent 与实验对比 Agent 汇总全部实验", 97, event_type="agent_started")
            call("report", {"id": "suite", "title": "过程报告"})
            process, _ = paper_agents.run_report_agent(current)
            db.update_paper_workspace(workspace_id, report_md=process)
            call("report", {"id": "suite", "title": "过程报告"}, "agent_returned")
            call("comparison", {"id": "suite", "title": "实验对比报告"})
            comparison, _ = paper_agents.run_comparison_agent(current)
            db.update_paper_workspace(workspace_id, comparison_report_md=comparison)
            call("comparison", {"id": "suite", "title": "实验对比报告"}, "agent_returned")
        except Exception as exc:
            jobs.reclaim_failed_workspace(workspace_id)
            # Keep the evidence reports if model synthesis is unavailable.
            failure = exc
    if failure:
        raise failure
    finished = int(time.time())
    db.update_paper_workspace(workspace_id, status="completed", stage="completed", finished_at=finished)
    db.add_paper_workspace_event(workspace_id, "completed", "succeeded", "实验编排完成，过程报告与实验对比报告已归档")
    jobs._task_update(task_id, status="succeeded", progress=100, result=comparison, finished_at=finished,
                      detail="全部实验已完成，两份报告已归档", event_type="succeeded", event_content="实验套件完成")
