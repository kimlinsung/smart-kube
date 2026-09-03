from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from backend import auth, db, k8s_client, paper_agents, paper_jobs
from backend.app import create_app


def fake_documents(_files):
    return [{
        "name": "design.yaml", "content_type": "application/yaml", "size": 100,
        "text": "正文：验证云边协同推理", "truncated": False, "extraction_issue": None,
    }]


def fake_intelligence(_documents):
    return {
        "title": "正文理解生成的云边协同实验",
        "goal": "根据正文验证云边协同推理链路",
        "summary": "从上传正文识别出的实验摘要",
        "domain": "云边协同",
        "acceptance_criteria": ["资源按层级成功调度"],
        "ambiguities": ["未提供负载命令"],
        "assumptions": ["采用最小资源配套"],
        "agent_trace": {"agent": "文档理解 Agent", "model": "test-model"},
    }


def fake_configuration(_documents, _intelligence, rule_evidence, mode):
    resources = rule_evidence["resources"] or [{
        "tier": "edge", "count": 1, "arch": "arm64", "image": "ubuntu:22.04",
        "cpu": "500m", "memory": "512Mi", "gpu": 0,
    }]
    return {
        "resources": [{**row, "reason": "正文与规则证据"} for row in resources],
        "workflow_steps": ["配置资源", "提交调度"],
        "analysis_plan": ["核验调度证据"] if mode == "full" else [],
        "assumptions": ["使用最小请求量"],
        "agent_trace": {"agent": "配置 Agent", "model": "test-model"},
    }


def fake_code(_documents, _intelligence, configuration):
    runs = []
    tier_indexes = {"cloud": 0, "edge": 0, "device": 0}
    for resource in configuration["resources"]:
        for _ in range(resource["count"]):
            tier_indexes[resource["tier"]] += 1
            target_index = tier_indexes[resource["tier"]]
            runs.append({
                "run_id": f"run-{len(runs) + 1}",
                "target_tier": resource["tier"],
                "target_index": target_index,
                "arguments": ["--delay", str(target_index)],
                "purpose": "测量输出耗时",
            })
    return {
        "runtime": {
            "language": "python", "version": "3.11", "image": "python:3.11-slim",
            "filename": "agent_experiment.py", "entrypoint": "python", "timeout_seconds": 30,
        },
        "code": "import json\nprint(json.dumps({'status': 'ok', 'elapsed_seconds': 0.01}))\n",
        "runs": runs,
        "expected_observations": ["每个 Unit 输出实际耗时"],
        "assumptions": [],
        "agent_trace": {"agent": "代码生成 Agent", "model": "test-model"},
    }


def fake_analysis(_configuration, schedule, _events, retry=0):
    created = schedule.get("created", 0)
    requested = schedule.get("requested", 0)
    return {
        "verdict": "needs_attention",
        "summary": "调度已完成，但正文未提供工作负载执行命令。",
        "checks": [{
            "name": "调度证据", "passed": created == requested,
            "detail": f"已创建 {created}/{requested}", "evidence": "Kubernetes 调度返回值",
        }],
        "risks": ["尚未验证工作负载效果"],
        "recommendations": ["补充运行命令后重试分析"],
        "analysed_at": 1,
        "agent_trace": {"agent": "分析 Agent", "model": "test-model", "retry": retry},
    }


def fake_report(workspace):
    return (
        f"# {workspace['name']} 实验报告\n\n"
        "## 实验摘要\n\n这是由报告 Agent 根据测试证据生成的 Markdown 报告。\n\n"
        "## 风险\n\n尚未验证工作负载效果，资源等待用户手动回收。",
        {"agent": "报告 Agent", "model": "test-model"},
    )


def agent_patches(**overrides):
    values = {
        "extract_documents": fake_documents,
        "run_intent_agent": fake_intelligence,
        "run_config_agent": fake_configuration,
        "run_code_agent": fake_code,
        "run_analysis_agent": fake_analysis,
        "run_report_agent": fake_report,
    }
    values.update(overrides)
    return mock.patch.multiple("backend.paper_jobs.paper_agents", **values)


class TemporaryDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, "test.db")
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()


class PaperWorkspaceMigrationTest(TemporaryDatabaseTest):
    def test_legacy_workspace_files_keep_rows_and_default_to_input(self):
        os.remove(db.DB_PATH)
        with sqlite3.connect(db.DB_PATH) as connection:
            connection.execute(
                """
                CREATE TABLE paper_workspace_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    original_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    content_type TEXT,
                    created_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO paper_workspace_files("
                "workspace_id,user_id,original_name,stored_path,size,content_type,created_at"
                ") VALUES(?,?,?,?,?,?,?)",
                ("legacy-workspace", 7, "input.md", "/tmp/input.md", 12, "text/markdown", 100),
            )

        db.init_db()

        with sqlite3.connect(db.DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(paper_workspace_files)")
            }
            row = connection.execute(
                "SELECT * FROM paper_workspace_files WHERE workspace_id=?", ("legacy-workspace",)
            ).fetchone()
        self.assertIn("artifact_type", columns)
        self.assertEqual(row["original_name"], "input.md")
        self.assertEqual(row["artifact_type"], "input")


class PaperAgentAdapterTest(unittest.TestCase):
    def test_code_agent_generates_two_cloud_runs_with_distinct_delays(self):
        code = (
            "import argparse, json, time\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--delay', type=float, required=True)\n"
            "args = parser.parse_args()\n"
            "started = time.perf_counter()\n"
            "time.sleep(args.delay)\n"
            "print(json.dumps({'status': 'ok', 'elapsed_seconds': time.perf_counter() - started}))\n"
        )
        response = SimpleNamespace(
            content=json.dumps({
                "runtime": {"timeout_seconds": 30},
                "code": code,
                "runs": [
                    {"target_tier": "cloud", "target_index": 1, "arguments": ["--delay", "10"], "purpose": "10 秒测量"},
                    {"target_tier": "cloud", "target_index": 2, "arguments": ["--delay", "5"], "purpose": "5 秒测量"},
                ],
                "expected_observations": ["两个 Unit 分别输出约 10 秒和 5 秒"],
                "assumptions": [],
            }, ensure_ascii=False),
            usage_metadata={}, response_metadata={},
        )
        llm = mock.Mock()
        llm.invoke.return_value = response
        configuration = {"resources": [
            {
                "tier": "cloud", "count": 1, "arch": "amd64", "image": "ubuntu:22.04",
                "cpu": "500m", "memory": "512Mi", "gpu": 0,
            },
            {
                "tier": "cloud", "count": 1, "arch": "amd64", "image": "ubuntu:22.04",
                "cpu": "500m", "memory": "512Mi", "gpu": 0,
            },
        ]}
        with mock.patch("backend.paper_agents._make_llm", return_value=llm):
            result = paper_agents.run_code_agent(fake_documents([]), fake_intelligence([]), configuration)

        self.assertEqual(result["runtime"]["image"], "python:3.11-slim")
        self.assertEqual(result["runs"][0]["arguments"], ["--delay", "10"])
        self.assertEqual(result["runs"][1]["arguments"], ["--delay", "5"])
        compile(result["code"], result["runtime"]["filename"], "exec")

    def test_intent_agent_accepts_fenced_json_and_validates_metadata(self):
        response = SimpleNamespace(
            content="""```json
{"title":"正文标题","goal":"验证正文目标","summary":"正文摘要","domain":"边缘计算",
 "acceptance_criteria":["成功调度"],"ambiguities":[],"assumptions":["最小配置"]}
```""",
            usage_metadata={"input_tokens": 10, "output_tokens": 20},
            response_metadata={"finish_reason": "stop"},
        )
        llm = mock.Mock()
        llm.invoke.return_value = response
        with mock.patch("backend.paper_agents._make_llm", return_value=llm):
            result = paper_agents.run_intent_agent(fake_documents([]))

        self.assertEqual(result["title"], "正文标题")
        self.assertEqual(result["agent_trace"]["usage"]["output_tokens"], 20)
        prompt_payload = json.loads(llm.invoke.call_args.args[0][1].content)
        self.assertIn("验证云边协同推理", prompt_payload["documents"][0]["text"])

    def test_analysis_agent_does_not_send_ssh_secrets_to_model(self):
        response = SimpleNamespace(
            content=json.dumps({
                "verdict": "needs_attention",
                "summary": "只验证了调度",
                "checks": [{
                    "name": "调度", "passed": True, "detail": "已落位", "evidence": "Pod 返回值",
                }],
                "risks": ["未运行负载"],
                "recommendations": ["补充命令"],
            }, ensure_ascii=False),
            usage_metadata={}, response_metadata={},
        )
        llm = mock.Mock()
        llm.invoke.return_value = response
        schedule = {
            "requested": 1, "created": 1,
            "placements": [{
                "pod_name": "unit-a", "node": "edge-1", "ssh_password": "top-secret",
                "ssh_command": "ssh root@example", "token": "private-token",
            }],
        }
        with mock.patch("backend.paper_agents._make_llm", return_value=llm):
            result = paper_agents.run_analysis_agent({}, schedule, [])

        serialized_prompt = llm.invoke.call_args.args[0][1].content
        self.assertEqual(result["verdict"], "needs_attention")
        self.assertNotIn("top-secret", serialized_prompt)
        self.assertNotIn("private-token", serialized_prompt)
        self.assertNotIn("ssh root@example", serialized_prompt)

    def test_json_agent_retries_once_when_model_format_is_invalid(self):
        valid = json.dumps({
            "title": "修复后的标题", "goal": "修复后的目标", "summary": "修复后的摘要",
            "domain": "系统", "acceptance_criteria": ["合法 JSON"],
            "ambiguities": [], "assumptions": [],
        }, ensure_ascii=False)
        llm = mock.Mock()
        llm.invoke.side_effect = [
            SimpleNamespace(content='{"title": "缺少结尾"', usage_metadata={}, response_metadata={}),
            SimpleNamespace(content=valid, usage_metadata={}, response_metadata={}),
        ]
        with mock.patch("backend.paper_agents._make_llm", return_value=llm):
            result = paper_agents.run_intent_agent(fake_documents([]))

        self.assertEqual(result["title"], "修复后的标题")
        self.assertEqual(result["agent_trace"]["attempts"], 2)
        self.assertTrue(result["agent_trace"]["format_repaired"])
        self.assertEqual(llm.invoke.call_count, 2)

    def test_analysis_guardrail_rejects_passed_verdict_with_open_risks(self):
        response = SimpleNamespace(
            content=json.dumps({
                "verdict": "passed", "summary": "调度成功但负载未验证",
                "checks": [{"name": "调度", "passed": True, "detail": "已落位", "evidence": "Pod"}],
                "risks": ["工作负载未运行"], "recommendations": ["运行负载"],
            }, ensure_ascii=False),
            usage_metadata={}, response_metadata={},
        )
        llm = mock.Mock()
        llm.invoke.return_value = response
        with mock.patch("backend.paper_agents._make_llm", return_value=llm):
            result = paper_agents.run_analysis_agent({}, {"placements": []}, [])

        self.assertEqual(result["verdict"], "needs_attention")
        self.assertIn("verdict_guardrail", result["agent_trace"])


class KubernetesStartupTest(unittest.TestCase):
    def test_namespace_check_has_bounded_network_timeout(self):
        with mock.patch.object(k8s_client, "core_v1") as core_v1:
            k8s_client.ensure_namespace()

        core_v1.read_namespace.assert_called_once_with(
            k8s_client.NAMESPACE,
            _request_timeout=k8s_client._STARTUP_REQUEST_TIMEOUT,
        )

    def test_legacy_pod_migration_list_has_bounded_network_timeout(self):
        with mock.patch.object(k8s_client, "core_v1") as core_v1:
            core_v1.list_namespaced_pod.return_value.items = []
            migrated = k8s_client.migrate_unlabeled_pods_to(mock.Mock())

        self.assertEqual(migrated, 0)
        core_v1.list_namespaced_pod.assert_called_once_with(
            k8s_client.NAMESPACE,
            _request_timeout=k8s_client._STARTUP_REQUEST_TIMEOUT,
        )


class KubernetesSchedulingFallbackTest(unittest.TestCase):
    def test_workspace_fallback_relaxes_gpu_then_node_type(self):
        nodes = [
            {
                "name": "cpu-edge", "hostname": "cpu-edge", "arch": "amd64",
                "node_type": "edge", "ready": "True", "allocatable": {}, "capacity": {},
            },
        ]
        with mock.patch.object(k8s_client, "list_nodes", return_value=nodes):
            node, selection = k8s_client._select_node_with_fallback(
                arch="amd64", hostname=None, node_type="cloud", gpu=1,
                allow_constraint_fallback=True,
            )

        self.assertEqual(node["name"], "cpu-edge")
        self.assertEqual(selection["effective"], {
            "arch": "amd64", "hostname": None, "node_type": None, "gpu": 0,
        })
        self.assertEqual(selection["relaxed"], ["gpu", "node_type"])

    def test_without_workspace_fallback_constraints_remain_strict(self):
        nodes = [
            {
                "name": "cpu-edge", "hostname": "cpu-edge", "arch": "amd64",
                "node_type": "edge", "ready": "True", "allocatable": {}, "capacity": {},
            },
        ]
        with mock.patch.object(k8s_client, "list_nodes", return_value=nodes):
            node, selection = k8s_client._select_node_with_fallback(
                arch="amd64", hostname=None, node_type="cloud", gpu=1,
                allow_constraint_fallback=False,
            )

        self.assertIsNone(node)
        self.assertEqual(selection["relaxed"], [])


class PaperWorkspaceJobTest(TemporaryDatabaseTest):
    def test_execution_timeout_is_persisted_as_timed_out(self):
        run = {
            "run_id": "run-1", "target_tier": "cloud", "target_index": 1,
            "arguments": ["--delay", "10"], "purpose": "超时测试",
        }
        placement = {
            "pod_name": "unit-cloud", "node": "cloud-1", "arch": "amd64",
        }
        with mock.patch("backend.paper_jobs.time.time", return_value=101.5):
            result = paper_jobs._parse_execution_result(
                {
                    "stdout": "partial output\n",
                    "stderr": "terminated\n__SMARTKUBE_EXIT_CODE__=124\n",
                    "timed_out": False,
                },
                100.0,
                run,
                placement,
                ["python", "/tmp/agent_experiment.py", "--delay", "10"],
            )

        self.assertEqual(result["status"], "timed_out")
        self.assertEqual(result["exit_code"], 124)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["duration_seconds"], 1.5)
        self.assertNotIn("__SMARTKUBE_EXIT_CODE__", result["stderr"])

    def test_zero_exit_without_structured_observation_is_not_success(self):
        with mock.patch("backend.paper_jobs.time.time", return_value=101.0):
            result = paper_jobs._parse_execution_result(
                {
                    "stdout": "hello world\n",
                    "stderr": "__SMARTKUBE_EXIT_CODE__=0\n",
                    "timed_out": False,
                },
                100.0,
                {
                    "run_id": "run-1", "target_tier": "cloud", "target_index": 1,
                    "arguments": [], "purpose": "输出测试",
                },
                {"pod_name": "unit-cloud", "node": "cloud-1", "arch": "amd64"},
                ["python", "/tmp/agent_experiment.py"],
            )

        self.assertEqual(result["status"], "invalid_output")
        self.assertFalse(result["observation_valid"])
        self.assertIsNone(result["observation"])

    def test_running_workspace_is_restored_as_interrupted(self):
        user, _ = auth.create_user("restart-runner", "secret123")
        experiment = db.create_experiment(user["id"], "重启恢复")
        workspace = db.create_paper_workspace(
            user["id"], experiment["id"], "重启恢复", "验证恢复", "full", {}
        )
        db.update_paper_workspace(workspace["id"], status="running", stage="schedule")

        self.assertEqual(db.interrupt_incomplete_paper_workspaces(), 1)
        restored = db.get_paper_workspace(workspace["id"], user_id=user["id"])
        self.assertEqual(restored["status"], "interrupted")
        self.assertEqual(restored["events"][-1]["event_type"], "interrupted")

    def test_full_workflow_persists_artifacts_and_keeps_resources(self):
        user, error = auth.create_user("paper-runner", "secret123")
        self.assertIsNone(error)
        experiment = db.create_experiment(user["id"], "跨架构实验")
        workspace = db.create_paper_workspace(
            user["id"], experiment["id"], "跨架构实验", "验证云边协同推理", "full",
            {},
        )
        source_path = os.path.join(self.temp_dir.name, "design.yaml")
        with open(source_path, "w", encoding="utf-8") as handle:
            handle.write(
                "resources:\n"
                "  cloud: {count: 1, arch: amd64, image: 'ubuntu:22.04'}\n"
                "  edge: {count: 1, arch: arm64, image: 'ubuntu:22.04'}\n"
            )
        db.add_paper_workspace_file(
            workspace["id"], user["id"], "design.yaml", source_path,
            os.path.getsize(source_path), "application/yaml",
        )
        task = db.create_execution_task(
            user["id"], experiment["id"], "paper", workspace["name"],
            metadata={"workspace_id": workspace["id"]},
        )
        sequence = iter([("cloud", "cloud-1", "amd64"), ("edge", "edge-1", "arm64")])

        def fake_create(*args, **kwargs):
            tier, node, arch = next(sequence)
            return {
                "pod_name": f"unit-{tier}", "node": node, "arch": arch, "node_type": tier,
                "image": kwargs["image"], "ssh_port": 31000, "ssh_user": "root",
                "ssh_password": "test", "ssh_command": "ssh test", "experiment_id": experiment["id"],
                "gpu": kwargs["gpu"],
            }

        def fake_exec(pod_name, command, timeout=60):
            if command[:2] == ["mkdir", "-p"]:
                return {"stdout": "", "stderr": "", "timed_out": False}
            elapsed = "1.001" if pod_name == "unit-cloud" else "2.002"
            return {
                "stdout": f'{{"status":"ok","elapsed_seconds":{elapsed}}}\n',
                "stderr": "\n__SMARTKUBE_EXIT_CODE__=0\n",
                "timed_out": False,
            }

        with agent_patches(), mock.patch("backend.paper_jobs.k8s_client.create_ssh_pod", side_effect=fake_create) as create_pod, mock.patch(
            "backend.paper_jobs.k8s_client.delete_pods_by_experiment"
        ) as delete_resources, mock.patch(
            "backend.paper_jobs.k8s_client.describe_pod",
            return_value={"phase": "Running", "container_statuses": [{"ready": True}]},
        ), mock.patch(
            "backend.paper_jobs.k8s_client.copy_to_pod", return_value="/tmp/smart-kube-experiment/agent_experiment.py"
        ), mock.patch(
            "backend.paper_jobs.k8s_client.exec_in_pod", side_effect=fake_exec
        ), mock.patch("backend.paper_jobs.task_events.publish_task"):
            paper_jobs._execute_workspace(workspace["id"], task["id"], user, "203.0.113.30")

        completed = db.get_paper_workspace(workspace["id"], user_id=user["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["stage"], "completed")
        self.assertEqual(completed["schedule_json"]["created"], 2)
        self.assertEqual(completed["schedule_json"]["execution_summary"]["succeeded"], 2)
        self.assertEqual(len(completed["schedule_json"]["executions"]), 2)
        self.assertIn("elapsed_seconds", completed["schedule_json"]["executions"][0]["stdout"])
        self.assertTrue(completed["schedule_json"]["executions"][0]["observation_valid"])
        self.assertTrue(any(file["artifact_type"] == "generated_code" for file in completed["files"]))
        self.assertTrue(all(call.kwargs["isolated"] for call in create_pod.call_args_list))
        self.assertTrue(all(call.kwargs["allow_constraint_fallback"] for call in create_pod.call_args_list))
        self.assertEqual(completed["name"], "正文理解生成的云边协同实验")
        self.assertEqual(completed["goal"], "根据正文验证云边协同推理链路")
        self.assertEqual(completed["analysis_json"]["verdict"], "needs_attention")
        self.assertEqual(completed["config_json"]["document_intelligence"]["domain"], "云边协同")
        self.assertEqual(db.get_experiment(experiment["id"])["name"], completed["name"])
        self.assertIn("# 正文理解生成的云边协同实验 实验报告", completed["report_md"])
        self.assertFalse(completed["resources_reclaimed"])
        self.assertTrue(any(event["event_type"] == "placement" for event in completed["events"]))
        completed_phases = [
            event["phase"] for event in completed["events"]
            if event["event_type"] == "agent_completed"
        ]
        self.assertLess(completed_phases.index("config"), completed_phases.index("code"))
        config_event = next(
            event for event in completed["events"]
            if event["phase"] == "config" and event["event_type"] == "agent_completed"
        )
        self.assertNotIn("generated_program", config_event["data"])
        delete_resources.assert_not_called()

    def test_partial_schedule_is_persisted_when_later_placement_fails(self):
        user, _ = auth.create_user("partial-runner", "secret123")
        experiment = db.create_experiment(user["id"], "部分调度")
        workspace = db.create_paper_workspace(
            user["id"], experiment["id"], "部分调度", "测试失败保留", "resources",
            {},
        )
        path = os.path.join(self.temp_dir.name, "input.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("resources:\n  cloud: {count: 2, arch: amd64, image: 'ubuntu:22.04'}\n")
        db.add_paper_workspace_file(
            workspace["id"], user["id"], "input.yaml", path, os.path.getsize(path), "application/yaml"
        )
        task = db.create_execution_task(user["id"], experiment["id"], "paper", "部分调度")
        placement = {
            "pod_name": "unit-cloud", "node": "cloud-1", "arch": "amd64", "node_type": "cloud",
            "image": "ubuntu:22.04", "ssh_port": 31000, "ssh_user": "root", "ssh_password": "test",
            "ssh_command": "ssh test", "experiment_id": experiment["id"], "gpu": 0,
        }
        with agent_patches(), mock.patch(
            "backend.paper_jobs.k8s_client.create_ssh_pod", side_effect=[placement, RuntimeError("capacity exhausted")]
        ), mock.patch("backend.paper_jobs.task_events.publish_task"):
            paper_jobs._execute_workspace(workspace["id"], task["id"], user, "203.0.113.31")

        failed = db.get_paper_workspace(workspace["id"], user_id=user["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["schedule_json"]["created"], 1)
        self.assertTrue(failed["schedule_json"]["resources_retained"])

    def test_llm_failure_is_visible_and_does_not_schedule(self):
        user, _ = auth.create_user("agent-failure", "secret123")
        experiment = db.create_experiment(user["id"], "临时实验")
        workspace = db.create_paper_workspace(
            user["id"], experiment["id"], "等待理解", "等待理解", "full", {}
        )
        path = os.path.join(self.temp_dir.name, "input.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("# 一个真实实验需求")
        db.add_paper_workspace_file(
            workspace["id"], user["id"], "input.md", path, os.path.getsize(path), "text/markdown"
        )
        task = db.create_execution_task(user["id"], experiment["id"], "paper", "等待理解")

        failure = paper_jobs.paper_agents.PaperAgentError("文档理解 Agent 大模型调用失败：timeout")
        with agent_patches(run_intent_agent=mock.Mock(side_effect=failure)), mock.patch(
            "backend.paper_jobs.k8s_client.create_ssh_pod"
        ) as create_pod, mock.patch("backend.paper_jobs.task_events.publish_task"):
            paper_jobs._execute_workspace(workspace["id"], task["id"], user, "203.0.113.32")

        failed = db.get_paper_workspace(workspace["id"], user_id=user["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["stage"], "intake")
        self.assertIn("大模型调用失败", failed["events"][-1]["content"])
        create_pod.assert_not_called()

    def test_analysis_retry_calls_analysis_and_report_agents_again(self):
        user, _ = auth.create_user("retry-agent", "secret123")
        experiment = db.create_experiment(user["id"], "重试实验")
        workspace = db.create_paper_workspace(
            user["id"], experiment["id"], "重试实验", "重新评估证据", "full", {}
        )
        db.update_paper_workspace(
            workspace["id"], status="completed", stage="completed",
            config_json={"resources": [{"tier": "edge", "count": 1}]},
            schedule_json={"requested": 1, "created": 1, "placements": []},
            analysis_json={"verdict": "needs_attention"}, report_md="# old",
        )
        task = db.create_execution_task(user["id"], experiment["id"], "paper_analysis", "重新分析")
        analyse = mock.Mock(side_effect=fake_analysis)
        report = mock.Mock(side_effect=fake_report)

        with agent_patches(run_analysis_agent=analyse, run_report_agent=report), mock.patch(
            "backend.paper_jobs.task_events.publish_task"
        ):
            paper_jobs._execute_analysis_retry(
                workspace["id"], task["id"], user, "203.0.113.33"
            )

        completed = db.get_paper_workspace(workspace["id"], user_id=user["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["retries"], 1)
        self.assertEqual(analyse.call_count, 1)
        self.assertEqual(analyse.call_args.kwargs["retry"], 1)
        self.assertEqual(report.call_count, 1)
        self.assertNotEqual(completed["report_md"], "# old")


class PaperWorkspaceApiTest(TemporaryDatabaseTest):
    def setUp(self):
        super().setUp()
        self.upload_patch = mock.patch("backend.routes_api.UPLOAD_DIR", self.temp_dir.name)
        self.upload_patch.start()
        with mock.patch("backend.k8s_client.ensure_namespace"), mock.patch(
            "backend.k8s_client.migrate_unlabeled_pods_to", return_value=0
        ):
            self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        with db.cursor() as cur:
            cur.execute("SELECT id FROM users ORDER BY id LIMIT 1")
            self.user_id = cur.fetchone()["id"]
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id

    def tearDown(self):
        self.upload_patch.stop()
        super().tearDown()

    def test_create_requires_mode_and_creates_one_experiment_with_files(self):
        missing_mode = self.client.post(
            "/api/paper/workspaces",
            data={"goal": "test", "resource_spec": "{}", "files": (io.BytesIO(b"x"), "a.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(missing_mode.status_code, 400)

        with mock.patch("backend.routes_api.paper_jobs.start_workspace_job", return_value={"id": "task-1"}), mock.patch(
            "backend.routes_api.k8s_client.list_pods_by_experiment", return_value=[]
        ):
            response = self.client.post(
                "/api/paper/workspaces",
                data={
                    "name": "", "goal": "", "mode": "full",
                    "files": [
                        (io.BytesIO(b"# edge workload\nprint('ok')\n"), "main.py"),
                        (io.BytesIO(b"# design\n"), "design.md"),
                    ],
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 202)
        workspace = response.get_json()["workspace"]
        self.assertEqual(workspace["mode"], "full")
        self.assertEqual(len(workspace["files"]), 2)
        self.assertTrue(workspace["name"].startswith("正在理解输入-"))
        self.assertIn("文档理解 Agent", workspace["goal"])
        self.assertTrue(db.get_experiment(workspace["experiment_id"]))
        with self.client.session_transaction() as session:
            self.assertEqual(session["current_experiment_id"], workspace["experiment_id"])

    def test_reclaim_is_explicit_and_keeps_workspace_artifacts(self):
        experiment = db.create_experiment(self.user_id, "待回收实验")
        workspace = db.create_paper_workspace(
            self.user_id, experiment["id"], "待回收实验", "保留报告", "full",
            {"cloud": {"count": 1}},
        )
        db.update_paper_workspace(
            workspace["id"], status="completed", stage="completed",
            schedule_json={"created": 1, "placements": [{"pod_name": "unit-a"}]},
            report_md="# persisted",
        )
        with mock.patch("backend.routes_api.k8s_client.delete_pods_by_experiment", return_value=["unit-a"]), mock.patch(
            "backend.routes_api.k8s_client.list_pods_by_experiment", return_value=[]
        ):
            response = self.client.post(f"/api/paper/workspaces/{workspace['id']}/reclaim")

        self.assertEqual(response.status_code, 200)
        persisted = db.get_paper_workspace(workspace["id"], user_id=self.user_id)
        self.assertTrue(persisted["resources_reclaimed"])
        self.assertEqual(persisted["report_md"], "# persisted")
        self.assertTrue(db.get_experiment(experiment["id"]))

    def test_delete_workspace_removes_resources_records_and_artifacts(self):
        experiment = db.create_experiment(self.user_id, "待删除工作区")
        workspace = db.create_paper_workspace(
            self.user_id, experiment["id"], "待删除工作区", "彻底清理", "full", {}
        )
        workspace_dir = os.path.join(
            self.temp_dir.name, str(self.user_id), "paper", workspace["id"]
        )
        os.makedirs(workspace_dir)
        input_path = os.path.join(workspace_dir, "input.md")
        generated_path = os.path.join(workspace_dir, "agent_experiment.py")
        with open(input_path, "w", encoding="utf-8") as handle:
            handle.write("input")
        with open(generated_path, "w", encoding="utf-8") as handle:
            handle.write("generated")
        db.add_paper_workspace_file(
            workspace["id"], self.user_id, "input.md", input_path, 5, "text/markdown"
        )
        db.add_paper_workspace_file(
            workspace["id"], self.user_id, "agent_experiment.py", generated_path, 9,
            "text/x-python", artifact_type="generated_code",
        )
        task = db.create_execution_task(
            self.user_id, experiment["id"], "paper", "待删除工作区",
            metadata={"workspace_id": workspace["id"]},
        )
        db.update_paper_workspace(workspace["id"], status="completed", stage="completed")

        with mock.patch("backend.routes_api.k8s_client.delete_pods_by_experiment", return_value=["unit-a"]):
            response = self.client.delete(f"/api/paper/workspaces/{workspace['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["deleted_pods"], ["unit-a"])
        self.assertIsNone(db.get_paper_workspace(workspace["id"], user_id=self.user_id))
        self.assertIsNone(db.get_experiment(experiment["id"]))
        self.assertIsNone(db.get_execution_task(task["id"], user_id=self.user_id))
        self.assertFalse(os.path.exists(workspace_dir))

    def test_admin_can_read_another_users_workspace(self):
        experiment = db.create_experiment(self.user_id + 999, "私有工作区")
        workspace = db.create_paper_workspace(
            self.user_id + 999, experiment["id"], "私有工作区", "private", "resources",
            {"cloud": {"count": 1}},
        )
        with mock.patch("backend.routes_api.k8s_client.list_pods_by_experiment", return_value=[]):
            response = self.client.get(f"/api/paper/workspaces/{workspace['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["workspace"]["access_role"], "admin")

    def test_only_full_workflow_can_retry_analysis(self):
        full_experiment = db.create_experiment(self.user_id, "完整流程")
        full = db.create_paper_workspace(
            self.user_id, full_experiment["id"], "完整流程", "retry", "full", {}
        )
        db.update_paper_workspace(full["id"], status="completed", stage="completed")
        resource_experiment = db.create_experiment(self.user_id, "资源流程")
        resources = db.create_paper_workspace(
            self.user_id, resource_experiment["id"], "资源流程", "no retry", "resources", {}
        )
        db.update_paper_workspace(resources["id"], status="completed", stage="completed")

        with mock.patch("backend.routes_api.paper_jobs.start_analysis_retry", return_value={"id": "retry-task"}) as start:
            response = self.client.post(f"/api/paper/workspaces/{full['id']}/analysis/retry")
        self.assertEqual(response.status_code, 202)
        start.assert_called_once()
        denied = self.client.post(f"/api/paper/workspaces/{resources['id']}/analysis/retry")
        self.assertEqual(denied.status_code, 400)


if __name__ == "__main__":
    unittest.main()
