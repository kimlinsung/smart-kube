from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from langchain_core.messages import AIMessage
from langgraph.prebuilt import ToolNode
from kubernetes.client.rest import ApiException

from backend import auth, db, k8s_client, tools, project_lifecycle
from backend.app import create_app


class ProjectLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for target, value in [("backend.db.DB_PATH", os.path.join(self.temp.name, "test.db")),
                              ("backend.routes_api.UPLOAD_DIR", self.temp.name),
                              ("backend.tools.UPLOAD_DIR", self.temp.name),
                              ("backend.project_lifecycle.UPLOAD_DIR", self.temp.name)]:
            patch = mock.patch(target, value)
            patch.start(); self.addCleanup(patch.stop)
        with mock.patch("backend.k8s_client.ensure_namespace"), mock.patch("backend.k8s_client.migrate_unlabeled_pods_to", return_value=0):
            self.app = create_app()
        self.app.config.update(TESTING=True)
        self.user, _ = auth.create_user("project-owner", "secret123")
        self.other, _ = auth.create_user("project-other", "secret123")
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user["id"]
        self.exp = db.create_experiment(self.user["id"], "test", "")
        tools.set_user(self.user)
        self.addCleanup(lambda: tools.set_user(None))
        patch = mock.patch("backend.k8s_client.delete_pods_by_experiment", return_value=["unit"])
        self.cleanup_pods = patch.start(); self.addCleanup(patch.stop)

    def workspace(self, exp=None):
        exp = exp or self.exp
        item = db.create_paper_workspace(exp["user_id"], exp["id"], "work", "test", "full", {})
        db.update_paper_workspace(item["id"], status="completed")
        path = os.path.join(self.temp.name, str(exp["user_id"]), "paper", item["id"], "nested")
        os.makedirs(path)
        with open(os.path.join(path, "output.txt"), "w") as handle:
            handle.write("generated")
        return item, os.path.dirname(path)

    def test_batch_partial_failure_and_duplicate_ids(self):
        foreign = db.create_experiment(self.other["id"], "private", "")
        response = self.client.post("/api/experiments/batch-delete", json={"ids": [self.exp["id"], foreign["id"], self.exp["id"]]})
        result = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][1]["status"], 403)
        self.assertIsNotNone(db.get_experiment(foreign["id"]))
        self.cleanup_pods.assert_called_once_with(self.exp["id"])

    def test_invalid_batch_does_not_mutate(self):
        for ids in [None, [], [True], ["1"], [1] * 51]:
            response = self.client.post("/api/experiments/batch-delete", json={"ids": ids})
            self.assertEqual(response.status_code, 400)
        self.cleanup_pods.assert_not_called()

    def test_workspace_deletion_cleans_unregistered_generated_content(self):
        workspace, path = self.workspace()
        response = self.client.post("/api/paper/workspaces/batch-delete", json={"ids": [workspace["id"]]})
        self.assertTrue(response.get_json()["ok"])
        self.assertFalse(os.path.exists(path))
        self.assertIsNone(db.get_experiment(self.exp["id"]))

    def test_experiment_deletion_uses_same_workspace_cleanup(self):
        _, path = self.workspace()
        self.assertEqual(self.client.delete(f"/api/experiments/{self.exp['id']}").status_code, 200)
        self.assertFalse(os.path.exists(path))

    def test_running_job_blocks_deletion_without_cleanup(self):
        self.workspace()
        db.create_execution_task(self.user["id"], self.exp["id"], "chat", "running")
        response = self.client.delete(f"/api/experiments/{self.exp['id']}")
        self.assertEqual(response.status_code, 409)
        self.cleanup_pods.assert_not_called()

    def test_cluster_failure_preserves_archive_and_database(self):
        _, path = self.workspace()
        self.cleanup_pods.side_effect = RuntimeError("cluster offline")
        self.assertEqual(self.client.delete(f"/api/experiments/{self.exp['id']}").status_code, 502)
        self.assertTrue(os.path.isdir(path))
        self.assertIsNotNone(db.get_experiment(self.exp["id"]))

    def test_admin_can_delete_workspace(self):
        foreign = db.create_experiment(self.other["id"], "private", "")
        workspace, path = self.workspace(foreign)
        with db.cursor() as cur:
            cur.execute("UPDATE users SET role='admin' WHERE id=?", (self.user["id"],))
        response = self.client.delete(f"/api/paper/workspaces/{workspace['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(os.path.exists(path))

    def test_tool_requires_confirmation_and_rejects_current_conversation(self):
        tools.set_user(self.user, experiment_id=self.exp["id"])
        self.assertIn("确认", tools.delete_projects.invoke({"ids": [str(self.exp["id"])]}))
        result = json.loads(tools.delete_projects.invoke({"ids": [str(self.exp["id"])], "confirmed": True}))
        self.assertFalse(result["ok"])
        self.cleanup_pods.assert_not_called()

    def test_tool_deletion_enforces_owner(self):
        tools.set_user(self.other)
        result = json.loads(tools.delete_projects.invoke({"ids": [str(self.exp["id"])], "confirmed": True}))
        self.assertEqual(result["results"][0]["status"], 403)
        self.cleanup_pods.assert_not_called()

    def test_tool_creates_experiment_without_allocating_compute(self):
        result = json.loads(tools.create_project.invoke({"name": "dialogue experiment"}))
        self.assertEqual(db.get_experiment(result["experiment_id"])["user_id"], self.user["id"])
        self.assertIsNone(db.get_paper_workspace_for_experiment(result["experiment_id"]))

    def test_toolnode_creates_workspace_with_flask_and_user_context(self):
        call = AIMessage(content="", tool_calls=[{"name": "create_project", "args": {"name": "reproduction", "kind": "workspace", "goal": "measure inference latency"}, "id": "create-1", "type": "tool_call"}])
        with self.app.app_context(), mock.patch("backend.paper_jobs.start_workspace_job", return_value={"id": "task"}) as start:
            result = ToolNode([tools.create_project]).invoke({"messages": [call]})
        data = json.loads(result["messages"][0].content)
        self.assertTrue(data["ok"])
        self.assertEqual(start.call_args.args[2]["id"], self.user["id"])
        workspace = db.get_paper_workspace(data["workspace_id"])
        self.assertEqual(workspace["mode"], "resources")

    def test_uploaded_input_is_copied_and_owned(self):
        directory = os.path.join(self.temp.name, str(self.user["id"]))
        os.makedirs(directory)
        source = os.path.join(directory, "input.md")
        with open(source, "w") as handle:
            handle.write("original")
        db.create_script_file(self.user["id"], self.exp["id"], "input.md", source, 8)
        tools.set_user(self.user, uploaded_file=source)
        with self.app.app_context(), mock.patch("backend.paper_jobs.start_workspace_job", return_value={"id": "task"}):
            data = json.loads(tools.create_project.invoke({"name": "copy", "kind": "workspace", "use_uploaded_file": True}))
        with db.cursor() as cur:
            copied = cur.execute("SELECT stored_path FROM paper_workspace_files WHERE workspace_id=?", (data["workspace_id"],)).fetchone()[0]
        self.assertNotEqual(source, copied)
        self.client.delete(f"/api/experiments/{self.exp['id']}")
        self.assertTrue(os.path.isfile(copied))
        tools.set_user(self.other, uploaded_file=copied)
        self.assertIn("本人", tools.create_project.invoke({"name": "bad", "kind": "workspace", "use_uploaded_file": True}))

    def test_fallback_does_not_create_pod_for_workspace_request(self):
        for text in ["创建一个 GPU 实验", "删除工作区", "create experiment"]:
            self.assertEqual(tools.fallback_parse(text)["action"], "project_clarify")

    def test_deleted_experiment_cannot_admit_new_job(self):
        project_lifecycle.delete_project(self.user, self.exp["id"])
        with self.assertRaisesRegex(ValueError, "已删除"):
            db.create_execution_task(self.user["id"], self.exp["id"], "chat", "late", require_experiment=True)

    def test_preview_reuses_workspace_access_checks_and_rejects_active_html(self):
        workspace, directory = self.workspace()
        path = os.path.join(directory, "untrusted.html")
        with open(path, "w") as handle:
            handle.write("<script>attack()</script>")
        item = db.add_paper_workspace_file(workspace["id"], self.user["id"], "untrusted.html", path, 25, "text/html")
        base = f"/api/paper/workspaces/{workspace['id']}/files/{item['id']}"
        self.assertEqual(self.client.get(base + "/preview").status_code, 415)
        self.assertEqual(self.client.get(base + "/content").get_json()["kind"], "text")
        with self.client.session_transaction() as session:
            session["user_id"] = self.other["id"]
        self.assertEqual(self.client.get(base + "/content").status_code, 404)
        self.assertEqual(self.client.get(base + "/preview").status_code, 404)

    def test_media_preview_has_sandbox_and_no_cache_headers(self):
        workspace, directory = self.workspace()
        path = os.path.join(directory, "sample.pdf")
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.7\n")
        item = db.add_paper_workspace_file(workspace["id"], self.user["id"], "sample.pdf", path, 9, "application/pdf")
        response = self.client.get(f"/api/paper/workspaces/{workspace['id']}/files/{item['id']}/preview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", response.headers["Content-Security-Policy"])
        self.assertIn("no-store", response.headers["Cache-Control"])
        response.close()

    def test_live_transition_projection_does_not_include_secrets_or_code(self):
        workspace, _ = self.workspace()
        db.add_paper_workspace_event(workspace["id"], "analysis", "retry_requested", "return",
                                    data={"from": "report", "to": "analysis", "attempt": 2, "api_key": "private-key", "code": "private-code"})
        response = self.client.get(f"/api/paper/workspaces/{workspace['id']}/status")
        data = response.get_json()
        self.assertEqual(data["workspace"]["events"][-1]["transition"]["from"], "report")
        self.assertNotIn("private-key", json.dumps(data))
        self.assertNotIn("private-code", json.dumps(data))


class ClusterCleanupTest(unittest.TestCase):
    def test_list_failure_is_not_success(self):
        with mock.patch.object(k8s_client, "core_v1") as core:
            core.list_namespaced_pod.side_effect = ApiException(status=503)
            with self.assertRaises(ApiException):
                k8s_client.delete_pods_by_experiment(1)
            core.delete_namespaced_pod.assert_not_called()

    def test_orphan_service_can_be_retried(self):
        with mock.patch.object(k8s_client, "core_v1") as core, mock.patch.object(k8s_client, "_release_ssh_port"):
            core.list_namespaced_pod.return_value.items = []
            core.list_namespaced_service.return_value.items = [SimpleNamespace(metadata=SimpleNamespace(name="orphan"))]
            self.assertEqual(k8s_client.delete_pods_by_experiment(1), [])
            self.assertEqual(core.delete_namespaced_service.call_args.args[0], "orphan")
