from __future__ import annotations

import io
import os
import tempfile
import unittest
from unittest import mock

from backend import auth, db, jobs
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


class ExecutionTaskPersistenceTest(TemporaryDatabaseTest):
    def test_running_task_is_restored_as_interrupted(self):
        task = db.create_execution_task(7, 3, "chat", "测试任务", "等待执行")
        db.update_execution_task(task["id"], status="running", progress=45, detail="正在执行")
        db.add_task_event(task["id"], "progress", "正在执行")

        self.assertEqual(db.get_execution_task(task["id"])["status"], "running")
        self.assertEqual(db.interrupt_incomplete_tasks(), 1)

        restored = db.get_execution_task(task["id"])
        self.assertEqual(restored["status"], "interrupted")
        self.assertIn("服务已重启", restored["error"])
        self.assertEqual(restored["events"][-1]["event_type"], "interrupted")

    def test_script_job_persists_stages_and_result(self):
        user, error = auth.create_user("runner", "secret123")
        self.assertIsNone(error)
        path = os.path.join(self.temp_dir.name, "hello.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("print('hello')\n")
        script = db.create_script_file(user["id"], 11, "hello.py", path, os.path.getsize(path))
        task = db.create_execution_task(user["id"], 11, "script", "运行 hello.py")

        def fake_run(*args, **kwargs):
            kwargs["progress_callback"]("正在创建临时 Python Pod", 25)
            kwargs["progress_callback"]("脚本已上传，正在执行", 68)
            return {"stdout": "hello\n", "stderr": "", "node": "edge-1", "pod_name": "pyexec-1"}

        with mock.patch("backend.jobs.k8s_client.run_python_oneshot", side_effect=fake_run), mock.patch(
            "backend.jobs.task_events.publish_task"
        ):
            jobs._execute_script(
                task["id"], user, script, 11,
                {"arch": "arm64", "hostname": None, "timeout": 120},
                "203.0.113.8",
            )

        completed = db.get_execution_task(task["id"])
        self.assertEqual(completed["status"], "succeeded")
        self.assertEqual(completed["progress"], 100)
        self.assertIn("hello", completed["result"])
        self.assertTrue(any(event["content"] == "脚本已上传，正在执行" for event in completed["events"]))
        with db.cursor() as cur:
            cur.execute("SELECT source_ip FROM audit_logs WHERE action='run_python'")
            self.assertEqual(cur.fetchone()["source_ip"], "203.0.113.8")

    def test_chat_job_persists_progress_and_completed_reply(self):
        user, error = auth.create_user("chat-runner", "secret123")
        self.assertIsNone(error)
        task = db.create_execution_task(user["id"], 12, "chat", "创建测试资源")

        def fake_stream(*args, **kwargs):
            kwargs["progress_callback"]("正在创建测试资源", 55)
            yield {"status": "正在等待资源就绪"}
            yield {"delta": "资源"}
            yield {"delta": "已创建"}

        with mock.patch("backend.jobs.agent.chat_stream", side_effect=fake_stream), mock.patch(
            "backend.jobs.task_events.publish_task"
        ):
            jobs._execute_chat(task["id"], user, "创建测试资源", None, 12, "203.0.113.9")

        completed = db.get_execution_task(task["id"])
        self.assertEqual(completed["status"], "succeeded")
        self.assertEqual(completed["progress"], 100)
        self.assertEqual(completed["result"], "资源已创建")
        self.assertTrue(any(event["content"] == "正在创建测试资源" for event in completed["events"]))
        self.assertTrue(any(event["content"] == "处理完成" for event in completed["events"]))


class ScriptApiTest(TemporaryDatabaseTest):
    def setUp(self):
        super().setUp()
        self.upload_dir_patch = mock.patch("backend.routes_api.UPLOAD_DIR", self.temp_dir.name)
        self.upload_dir_patch.start()
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
        self.upload_dir_patch.stop()
        super().tearDown()

    def test_upload_is_persisted_but_not_executed(self):
        with mock.patch("backend.jobs.start_script_task") as start_script:
            response = self.client.post(
                "/api/upload",
                data={"file": (io.BytesIO(b"print('ok')\n"), "demo.py")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["script"]["original_name"], "demo.py")
        self.assertNotIn("stored_path", payload["script"])
        self.assertEqual(payload["task"]["status"], "succeeded")
        self.assertIn("不会自动运行", payload["task"]["result"])
        start_script.assert_not_called()

        current = self.client.get("/api/scripts/current").get_json()["script"]
        self.assertEqual(current["id"], payload["script"]["id"])

    def test_user_cannot_run_another_users_script(self):
        path = os.path.join(self.temp_dir.name, "foreign.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("print('foreign')\n")
        foreign = db.create_script_file(self.user_id + 999, 1, "foreign.py", path, 17)

        response = self.client.post(f"/api/scripts/{foreign['id']}/run", json={})

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
