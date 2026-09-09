import io
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from backend import agent, auth, db, k8s_client, model_settings, paper_agents
from backend.app import create_app


class ModelAndBatchApiTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patch = mock.patch.object(db, "DB_PATH", os.path.join(self.directory.name, "test.db"))
        patch.start()
        self.addCleanup(patch.stop)
        db.init_db()
        with mock.patch.object(k8s_client, "ensure_namespace"), mock.patch.object(k8s_client, "migrate_unlabeled_pods_to"):
            self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self.user, _ = auth.create_user("owner", "secret123")
        with self.client.session_transaction() as session:
            session["user_id"] = self.user["id"]
        self.providers = {"test": {"api_base": "https://model.invalid/v1", "api_key": "private-test-key", "models": ["model-a", "model-b"]}}
        patch = mock.patch.object(model_settings, "LLM_PROVIDERS", self.providers)
        patch.start()
        self.addCleanup(patch.stop)

    def test_catalog_is_authenticated_and_never_returns_secrets(self):
        response = self.client.get("/api/models")
        self.assertEqual(response.status_code, 200)
        self.assertIn("test:model-a", [item["id"] for item in response.json["models"]])
        self.assertNotIn("api_key", response.text)
        self.assertNotIn("model.invalid", response.text)
        self.assertNotIn("private-test-key", response.text)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get("/api/models").status_code, 401)

    def test_preference_persists_and_is_user_specific(self):
        self.assertEqual(self.client.put("/api/me/model", json={"llm_profile": "test:model-b"}).status_code, 200)
        self.assertEqual(self.client.get("/api/me").json["llm_profile"], "test:model-b")
        other, _ = auth.create_user("other", "secret123")
        with self.client.session_transaction() as session:
            session["user_id"] = other["id"]
        self.assertEqual(self.client.get("/api/models").json["selected"], "default")

    def test_invalid_profile_rejected_before_task_creation(self):
        with mock.patch("backend.routes_api.jobs.start_chat_task") as start:
            response = self.client.post("/api/chat/tasks", json={"message": "hello", "llm_profile": "unconfigured"})
        self.assertEqual(response.status_code, 400)
        start.assert_not_called()

    def test_chat_task_snapshots_request_model(self):
        with mock.patch("backend.routes_api.jobs.start_chat_task", return_value={"id": "task"}) as start:
            response = self.client.post("/api/chat/tasks", json={"message": "hello", "llm_profile": "test:model-b"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(start.call_args.args[1]["llm_profile"], "test:model-b")
        self.client.put("/api/me/model", json={"llm_profile": "test:model-a"})
        self.assertEqual(start.call_args.args[1]["llm_profile"], "test:model-b")

    def test_paper_submission_passes_model_to_background_job(self):
        with mock.patch("backend.routes_api.UPLOAD_DIR", self.directory.name), mock.patch("backend.routes_api.paper_jobs.start_workspace_job", return_value={"id": "paper-task"}) as start, mock.patch.object(k8s_client, "list_pods_by_experiment", return_value=[]):
            response = self.client.post("/api/paper/workspaces", data={
                "mode": "full", "llm_profile": "test:model-a", "files": (io.BytesIO(b"hello"), "input.txt"),
            })
        self.assertEqual(response.status_code, 202)
        self.assertEqual(start.call_args.args[2]["llm_profile"], "test:model-a")

    def test_batch_deletion_checks_each_owner_and_deduplicates(self):
        def get_pod(name):
            return {"owner_id": self.user["id"] if name == "mine" else self.user["id"] + 1}
        with mock.patch.object(k8s_client, "get_pod", side_effect=get_pod), mock.patch.object(k8s_client.core_v1, "delete_namespaced_pod") as delete, mock.patch.object(k8s_client.core_v1, "delete_namespaced_service") as service:
            result = self.client.post("/api/resources/batch-delete", json={"pod_names": ["mine", "foreign", "mine"]})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["deleted"], ["mine"])
        self.assertEqual(result.json["failed"][0]["pod_name"], "foreign")
        delete.assert_called_once_with("mine", k8s_client.NAMESPACE)
        service.assert_called_once_with("mine", k8s_client.NAMESPACE)

    def test_invalid_batch_never_deletes_resources(self):
        with mock.patch.object(k8s_client, "delete_pod") as delete:
            for names in ([], ["../bad"], "mine", ["mine"] * 101, [None]):
                self.assertEqual(self.client.post("/api/resources/batch-delete", json={"pod_names": names}).status_code, 400)
            delete.assert_not_called()

    def test_batch_continues_after_one_failure(self):
        with mock.patch.object(k8s_client, "delete_pod", side_effect=[RuntimeError("failure"), None]):
            response = self.client.post("/api/resources/batch-delete", json={"pod_names": ["first", "second"]})
        self.assertEqual(response.json["deleted"], ["second"])
        self.assertEqual(response.json["failed"], [{"pod_name": "first", "error": "failure"}])

    def test_background_models_are_isolated_and_context_is_reset(self):
        barrier = threading.Barrier(2)

        @model_settings.task_model
        def run(user):
            barrier.wait(timeout=5)
            return paper_agents._trace(mock.Mock(usage_metadata={}, response_metadata={}), "test")["model"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, {"llm_profile": "test:model-" + suffix}) for suffix in ("a", "b")]
            self.assertEqual([future.result() for future in futures], ["model-a", "model-b"])
        self.assertEqual(model_settings._active.get(), "default")

    def test_client_uses_selected_provider_credentials(self):
        with mock.patch.object(agent, "ChatOpenAI") as client:
            agent._make_llm({"llm_profile": "test:model-b"})
        self.assertEqual(client.call_args.kwargs["model"], "model-b")
        self.assertEqual(client.call_args.kwargs["api_key"], "private-test-key")


if __name__ == "__main__":
    unittest.main()
