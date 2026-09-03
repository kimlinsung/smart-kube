from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from backend import auth, db, task_events
from backend.app import create_app


class ExperimentSharingTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, "test.db")
        with mock.patch("backend.k8s_client.ensure_namespace"), mock.patch(
            "backend.k8s_client.migrate_unlabeled_pods_to", return_value=0
        ):
            self.app = create_app()
        self.app.config.update(TESTING=True)
        self.owner, _ = auth.create_user("paper-owner", "secret123")
        self.collaborator, _ = auth.create_user("paper-reader", "secret123")
        self.stranger, _ = auth.create_user("paper-stranger", "secret123")
        self.experiment = db.create_experiment(self.owner["id"], "共享时延实验", "真实执行证据")
        self.workspace = db.create_paper_workspace(
            self.owner["id"], self.experiment["id"], "共享时延实验", "比较两个节点耗时", "full", {}
        )
        self.file_path = os.path.join(self.temp_dir.name, "input.md")
        with open(self.file_path, "w", encoding="utf-8") as handle:
            handle.write("# experiment input\n")
        self.file = db.add_paper_workspace_file(
            self.workspace["id"], self.owner["id"], "input.md", self.file_path,
            os.path.getsize(self.file_path), "text/markdown",
        )
        db.update_paper_workspace(
            self.workspace["id"], status="completed", stage="completed",
            config_json={
                "generated_program": {"code": "print('ok')", "agent_trace": {"provider": "private"}},
                "nested": {"api_key": "private-key", "password": "private-password"},
                "agent_trace": [{"model": "private-model"}],
            },
            schedule_json={
                "created": 1,
                "placements": [{
                    "pod_name": "unit-a", "node_type": "edge", "node": "edge-1",
                    "ssh_host": "private-host", "ssh_port": 31000,
                    "ssh_password": "private-password", "ssh_command": "ssh private",
                    "nested": {"access_token": "private-token"},
                }],
                "executions": [{
                    "pod_name": "unit-a", "status": "succeeded", "stdout": "ok",
                    "stderr": "", "duration_seconds": 1.25, "exit_code": 0,
                }],
            },
            analysis_json={
                "verdict": "passed", "checks": [{"name": "运行", "passed": True}],
                "agent_trace": {"provider": "private"},
            },
            report_md="# 实验报告\n\n真实结果。",
        )
        db.add_paper_workspace_event(
            self.workspace["id"], "execute", "succeeded", "Unit 执行完成",
            data={"token": "event-private-token", "agent_trace": {"provider": "private"}},
        )

    def tearDown(self):
        db.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def client_for(self, user=None):
        client = self.app.test_client()
        if user:
            with client.session_transaction() as session:
                session["user_id"] = user["id"]
        return client

    def add_collaborator(self):
        response = self.client_for(self.owner).post(
            f"/api/experiments/{self.experiment['id']}/collaborators",
            json={"username": self.collaborator["username"]},
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_existing_database_is_upgraded_without_losing_experiments(self):
        before = db.get_experiment(self.experiment["id"])
        db.init_db()
        after = db.get_experiment(self.experiment["id"])
        self.assertEqual(after["name"], before["name"])
        with db.cursor() as cur:
            names = {
                row["name"] for row in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("experiment_collaborators", names)
        self.assertIn("experiment_shares", names)

    def test_owner_can_add_and_remove_collaborator_by_username(self):
        payload = self.add_collaborator()
        self.assertEqual(payload["collaborators"][0]["username"], "paper-reader")
        duplicate = self.client_for(self.owner).post(
            f"/api/experiments/{self.experiment['id']}/collaborators",
            json={"username": self.collaborator["username"]},
        )
        self.assertFalse(duplicate.get_json()["added"])
        missing = self.client_for(self.owner).post(
            f"/api/experiments/{self.experiment['id']}/collaborators",
            json={"username": "does-not-exist"},
        )
        self.assertEqual(missing.status_code, 404)
        owner = self.client_for(self.owner).post(
            f"/api/experiments/{self.experiment['id']}/collaborators",
            json={"username": self.owner["username"]},
        )
        self.assertEqual(owner.status_code, 400)
        removed = self.client_for(self.owner).delete(
            f"/api/experiments/{self.experiment['id']}/collaborators/{self.collaborator['id']}"
        )
        self.assertTrue(removed.get_json()["removed"])

    def test_collaborator_can_read_artifacts_but_cannot_operate(self):
        self.add_collaborator()
        client = self.client_for(self.collaborator)
        with mock.patch("backend.routes_api.k8s_client.list_pods_by_experiment", return_value=[{
            "name": "unit-a", "node_type": "edge", "ssh_password": "private-password",
            "ssh_command": "ssh private", "token": "private-token",
        }]):
            experiments = client.get("/api/experiments").get_json()["experiments"]
            workspace_list = client.get("/api/paper/workspaces")
            detail = client.get(f"/api/experiments/{self.experiment['id']}")
            workspace = client.get(f"/api/paper/workspaces/{self.workspace['id']}")
        self.assertEqual(experiments[0]["access_role"], "collaborator")
        self.assertEqual(detail.status_code, 200)
        detail_text = json.dumps(detail.get_json(), ensure_ascii=False)
        self.assertNotIn("private-password", detail_text)
        self.assertNotIn("private-token", detail_text)
        self.assertEqual(workspace.status_code, 200)
        workspace_list_text = json.dumps(workspace_list.get_json(), ensure_ascii=False)
        self.assertNotIn("private-password", workspace_list_text)
        self.assertNotIn("private-key", workspace_list_text)
        self.assertNotIn("private-model", workspace_list_text)
        workspace_text = json.dumps(workspace.get_json(), ensure_ascii=False)
        self.assertNotIn("private-password", workspace_text)
        self.assertNotIn("private-key", workspace_text)
        self.assertNotIn("private-model", workspace_text)
        self.assertIn("print('ok')", workspace_text)
        self.assertEqual(
            client.get(f"/api/paper/workspaces/{self.workspace['id']}/files/{self.file['id']}/content").status_code,
            200,
        )
        download = client.get(
            f"/api/paper/workspaces/{self.workspace['id']}/files/{self.file['id']}/download"
        )
        self.assertEqual(download.status_code, 200)
        download.close()
        self.assertEqual(client.get(f"/api/paper/workspaces/{self.workspace['id']}/report").status_code, 200)
        self.assertEqual(client.post(f"/api/experiments/{self.experiment['id']}/enter").status_code, 403)
        self.assertEqual(client.post(f"/api/paper/workspaces/{self.workspace['id']}/analysis/retry").status_code, 403)
        self.assertEqual(client.post(f"/api/paper/workspaces/{self.workspace['id']}/reclaim").status_code, 403)
        self.assertEqual(client.get(f"/api/experiments/{self.experiment['id']}/sharing").status_code, 403)
        self.assertEqual(client.delete(f"/api/experiments/{self.experiment['id']}").status_code, 403)

    def test_stranger_cannot_read_project_or_file(self):
        client = self.client_for(self.stranger)
        self.assertEqual(client.get(f"/api/paper/workspaces/{self.workspace['id']}").status_code, 403)
        self.assertEqual(
            client.get(f"/api/paper/workspaces/{self.workspace['id']}/files/{self.file['id']}/download").status_code,
            404,
        )

    def test_share_is_idempotent_sanitized_audited_and_revocable(self):
        owner_client = self.client_for(self.owner)
        first = owner_client.post(f"/api/experiments/{self.experiment['id']}/share")
        second = owner_client.post(f"/api/experiments/{self.experiment['id']}/share")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["url"], second.get_json()["url"])
        token = first.get_json()["url"].split("token=", 1)[1]

        public = self.client_for().get(
            f"/api/public/experiments/shared/{token}",
            headers={"X-Real-IP": "203.0.113.55"},
        )
        self.assertEqual(public.status_code, 200)
        payload_text = json.dumps(public.get_json(), ensure_ascii=False)
        for secret in (
            "private-password", "private-key", "private-token", "private-model",
            "private-host", "ssh private", "agent_trace", "ssh_password", "ssh_command",
        ):
            self.assertNotIn(secret, payload_text)
        self.assertIn("print('ok')", payload_text)
        self.assertIn("真实结果", payload_text)

        download = self.client_for().get(
            f"/api/public/experiments/shared/{token}/files/{self.file['id']}/download",
            environ_base={"REMOTE_ADDR": "198.51.100.10"},
        )
        self.assertEqual(download.status_code, 200)
        download.close()
        with db.cursor() as cur:
            logs = [dict(row) for row in cur.execute(
                "SELECT username,action,source_ip FROM audit_logs "
                "WHERE action LIKE 'experiment_share_%' ORDER BY id"
            ).fetchall()]
        view = next(item for item in logs if item["action"] == "experiment_share_view")
        downloaded = next(item for item in logs if item["action"] == "experiment_share_download")
        self.assertEqual(view["username"], "unknown")
        self.assertEqual(view["source_ip"], "203.0.113.55")
        self.assertEqual(downloaded["username"], "unknown")
        self.assertEqual(downloaded["source_ip"], "198.51.100.10")

        revoked = owner_client.delete(f"/api/experiments/{self.experiment['id']}/share")
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(self.client_for().get(f"/api/public/experiments/shared/{token}").status_code, 404)
        replacement = owner_client.post(f"/api/experiments/{self.experiment['id']}/share").get_json()["url"]
        self.assertNotEqual(replacement, first.get_json()["url"])

    def test_public_download_cannot_cross_workspace_boundary(self):
        other_exp = db.create_experiment(self.owner["id"], "other")
        other_workspace = db.create_paper_workspace(
            self.owner["id"], other_exp["id"], "other", "other", "resources", {}
        )
        other_path = os.path.join(self.temp_dir.name, "other.txt")
        with open(other_path, "w", encoding="utf-8") as handle:
            handle.write("other")
        other_file = db.add_paper_workspace_file(
            other_workspace["id"], self.owner["id"], "other.txt", other_path, 5, "text/plain"
        )
        url = self.client_for(self.owner).post(
            f"/api/experiments/{self.experiment['id']}/share"
        ).get_json()["url"]
        token = url.split("token=", 1)[1]
        response = self.client_for().get(
            f"/api/public/experiments/shared/{token}/files/{other_file['id']}/download"
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_experiment_cleans_collaborator_and_share_rows(self):
        self.add_collaborator()
        self.client_for(self.owner).post(f"/api/experiments/{self.experiment['id']}/share")
        with mock.patch("backend.routes_api.k8s_client.delete_pods_by_experiment", return_value=[]):
            response = self.client_for(self.owner).delete(f"/api/experiments/{self.experiment['id']}")
        self.assertEqual(response.status_code, 200)
        with db.cursor() as cur:
            collaborator_count = cur.execute(
                "SELECT COUNT(*) AS count FROM experiment_collaborators WHERE experiment_id=?",
                (self.experiment["id"],),
            ).fetchone()["count"]
            share_count = cur.execute(
                "SELECT COUNT(*) AS count FROM experiment_shares WHERE experiment_id=?",
                (self.experiment["id"],),
            ).fetchone()["count"]
        self.assertEqual(collaborator_count, 0)
        self.assertEqual(share_count, 0)

    def test_task_event_for_collaborator_contains_only_refresh_metadata(self):
        db.add_experiment_collaborator(
            self.experiment["id"], self.collaborator["id"], self.owner["id"]
        )
        task = db.create_execution_task(
            self.owner["id"], self.experiment["id"], "paper", "private title",
            metadata={"workspace_id": self.workspace["id"], "token": "private-token"},
        )
        db.update_execution_task(task["id"], result="private result")
        with mock.patch("backend.task_events.publish") as publish:
            task_events.publish_task(task["id"])
        owner_call, collaborator_call = publish.call_args_list
        self.assertEqual(owner_call.args[0], self.owner["id"])
        self.assertEqual(owner_call.args[1]["type"], "task_update")
        self.assertEqual(collaborator_call.args[0], self.collaborator["id"])
        message = collaborator_call.args[1]
        self.assertEqual(message["type"], "workspace_task_update")
        self.assertEqual(message["task"]["metadata"], {"workspace_id": self.workspace["id"]})
        self.assertNotIn("result", message["task"])
        self.assertNotIn("events", message["task"])


if __name__ == "__main__":
    unittest.main()
