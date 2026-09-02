from __future__ import annotations

import io
import os
import tempfile
import unittest
from unittest import mock

from backend import auth, db, paper_jobs
from backend.app import create_app


class TemporaryDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, "test.db")
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()


class PaperWorkspaceJobTest(TemporaryDatabaseTest):
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

        with mock.patch("backend.paper_jobs.k8s_client.create_ssh_pod", side_effect=fake_create), mock.patch(
            "backend.paper_jobs.k8s_client.delete_pods_by_experiment"
        ) as delete_resources, mock.patch("backend.paper_jobs.task_events.publish_task"):
            paper_jobs._execute_workspace(workspace["id"], task["id"], user, "203.0.113.30")

        completed = db.get_paper_workspace(workspace["id"], user_id=user["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["stage"], "completed")
        self.assertEqual(completed["schedule_json"]["created"], 2)
        self.assertEqual(completed["analysis_json"]["verdict"], "passed")
        self.assertIn("# 跨架构实验 实验报告", completed["report_md"])
        self.assertFalse(completed["resources_reclaimed"])
        self.assertTrue(any(event["event_type"] == "placement" for event in completed["events"]))
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
        with mock.patch(
            "backend.paper_jobs.k8s_client.create_ssh_pod", side_effect=[placement, RuntimeError("capacity exhausted")]
        ), mock.patch("backend.paper_jobs.task_events.publish_task"):
            paper_jobs._execute_workspace(workspace["id"], task["id"], user, "203.0.113.31")

        failed = db.get_paper_workspace(workspace["id"], user_id=user["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["schedule_json"]["created"], 1)
        self.assertTrue(failed["schedule_json"]["resources_retained"])


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
        self.assertTrue(workspace["name"].startswith("main-"))
        self.assertIn("main.py", workspace["goal"])
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

    def test_other_user_cannot_read_workspace(self):
        experiment = db.create_experiment(self.user_id + 999, "私有工作区")
        workspace = db.create_paper_workspace(
            self.user_id + 999, experiment["id"], "私有工作区", "private", "resources",
            {"cloud": {"count": 1}},
        )
        response = self.client.get(f"/api/paper/workspaces/{workspace['id']}")
        self.assertEqual(response.status_code, 404)

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
