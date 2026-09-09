import gzip
import os
import tempfile
import time
import unittest
from unittest import mock

from backend import auth, db
from backend.app import create_app


class AccountSecurityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp.name, "security.db")
        with mock.patch("backend.k8s_client.ensure_namespace"), mock.patch(
            "backend.k8s_client.migrate_unlabeled_pods_to", return_value=0
        ):
            self.app = create_app()
        self.app.config.update(TESTING=True)
        self.password = "B7!Violet_river_2026"
        self.user, error = auth.create_user("researcher", self.password)
        self.assertIsNone(error)

    def tearDown(self):
        db.DB_PATH = self.old_db
        self.temp.cleanup()

    def client(self, user=None, **values):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = (user or self.user)["id"]
            session["credential_version"] = (user or self.user).get("credential_version", 0)
            session.update(values)
        return client

    def test_policy_is_enforced_on_creation_and_password_reset(self):
        for weak in ["short", "abcdefghijk123!", "ABCDEFGHIJK123!", "Abcdefghijklm!",
                     "Abcdefghijk123", "Abcd 98!efghi", "Password12345!", "Aa1!Aa1!Aa1!", None, 123]:
            self.assertIsNotNone(auth.validate_password(weak))
            self.assertIsNotNone(auth.change_password(self.user["id"], weak))
        user, error = auth.create_user("another", "simple")
        self.assertIsNone(user)
        self.assertIsNotNone(error)
        self.assertIsNotNone(auth.validate_password("researcher_!ABC98", "researcher"))
        self.assertIsNotNone(auth.validate_password("A" * 129))
        self.assertIsNone(auth.validate_password(self.password))

    def test_feishu_generates_unpredictable_secret_and_never_forces_initialization(self):
        with mock.patch("backend.auth.random_password", wraps=auth.random_password) as generate:
            user = auth.upsert_feishu_user({"open_id": "ou_example_alpha", "name": "张三"})
        generate.assert_called_once()
        self.assertEqual(user["password_generated"], 1)
        self.assertIsNone(auth.authenticate(user["username"], "!feishu-no-password!ou_example_alpha"))
        result = self.client(user).get("/api/me")
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("password_hash", result.get_json())
        again = auth.upsert_feishu_user({"open_id": "ou_example_alpha", "name": "张三"})
        self.assertEqual(again["password_hash"], user["password_hash"])
        samples = [auth.random_password() for _ in range(8)]
        self.assertEqual(len(set(samples)), 8)
        self.assertTrue(all(len(value) == 48 and auth.validate_password(value) is None for value in samples))

    def test_old_feishu_placeholder_is_disabled_and_rotated_but_custom_password_is_retained(self):
        user = auth.upsert_feishu_user({"open_id": "ou_example_beta"})
        predictable = "!feishu-no-password!ou_example_beta"
        with db.cursor() as cur:
            cur.execute("UPDATE users SET password_hash=?,password_generated=0 WHERE id=?",
                        (auth.generate_password_hash(predictable), user["id"]))
        self.assertIsNone(auth.authenticate(user["username"], predictable))
        rotated = auth.upsert_feishu_user({"open_id": "ou_example_beta"})
        self.assertEqual(rotated["password_generated"], 1)
        self.assertEqual(rotated["credential_version"], 1)
        auth.change_password(user["id"], self.password)
        custom = auth.upsert_feishu_user({"open_id": "ou_example_beta"})
        self.assertEqual(custom["password_generated"], 0)
        self.assertIsNotNone(auth.authenticate(custom["username"], self.password))

    def test_self_password_change_requires_proof_and_invalidates_other_sessions(self):
        client = self.client()
        other = self.client()
        new = "C8!Cobalt_ocean_2026"
        self.assertEqual(client.put("/api/me/password", json={"password": new}).status_code, 403)
        self.assertEqual(client.put("/api/me/password", json={"password": new, "current_password": self.password},
                                   headers={"Origin": "https://attacker.example"}).status_code, 403)
        response = client.put("/api/me/password", json={"password": new, "current_password": self.password})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get("/api/me").status_code, 200)
        self.assertEqual(other.get("/api/me").status_code, 401)
        self.assertIsNone(auth.authenticate(self.user["username"], self.password))
        self.assertIsNotNone(auth.authenticate(self.user["username"], new))
        fresh_login = self.app.test_client()
        self.assertEqual(fresh_login.post("/api/login", json={"username": self.user["username"], "password": new}).status_code, 200)
        self.assertEqual(fresh_login.get("/api/me").status_code, 200)

    def test_feishu_password_reset_requires_recent_oauth_and_consumes_proof(self):
        user = auth.upsert_feishu_user({"open_id": "ou_example_gamma"})
        for values in [{}, {"login_via": "feishu", "feishu_verified_at": time.time() - 601}]:
            self.assertEqual(self.client(user, **values).put("/api/me/password", json={"password": self.password}).status_code, 403)
        client = self.client(user, login_via="feishu", feishu_verified_at=time.time())
        self.assertTrue(client.get("/api/me").get_json()["can_reset_with_feishu"])
        self.assertEqual(client.put("/api/me/password", json={"password": self.password}).status_code, 200)
        self.assertFalse(client.get("/api/me").get_json()["can_reset_with_feishu"])
        self.assertEqual(client.put("/api/me/password", json={"password": self.password}).status_code, 403)

    def test_oauth_returns_to_requested_local_page_without_password_prompt(self):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["feishu_oauth_state"] = "test-state"
            session["feishu_oauth_next"] = "/dashboard.html?security=1"
        with mock.patch("backend.routes_feishu.feishu.is_enabled", return_value=True), mock.patch(
            "backend.routes_feishu.feishu.exchange_user_access_token", return_value={"access_token": "test"}
        ), mock.patch("backend.routes_feishu.feishu.fetch_user_info", return_value={"open_id": "ou_callback"}):
            response = client.get("/api/feishu/callback?code=test&state=test-state")
        self.assertEqual(response.location, "/dashboard.html?security=1")
        self.assertTrue(client.get("/api/me").get_json()["can_reset_with_feishu"])

    def test_candidate_search_is_scoped_minimal_and_literal(self):
        exp = db.create_experiment(self.user["id"], "research", "")
        candidate, _ = auth.create_user("candidate_01", self.password)
        with db.cursor() as cur:
            cur.execute("UPDATE users SET name=?, email=?, mobile=? WHERE id=?",
                        ("张三同学", "private@example.test", "private-phone", candidate["id"]))
        path = f"/api/experiments/{exp['id']}/collaborator-candidates"
        self.assertEqual(self.app.test_client().get(path + "?q=张三").status_code, 401)
        self.assertEqual(self.client(candidate).get(path + "?q=张三").status_code, 403)
        client = self.client()
        result = client.get(path, query_string={"q": "张三"}).get_json()["candidates"]
        self.assertEqual(result, [{"id": candidate["id"], "username": candidate["username"], "name": "张三同学"}])
        for query in ["", "张", "%_", "researcher"]:
            self.assertEqual(client.get(path, query_string={"q": query}).get_json()["candidates"], [])
        db.add_experiment_collaborator(exp["id"], candidate["id"], self.user["id"])
        self.assertEqual(client.get(path + "?q=candidate").get_json()["candidates"], [])
        self.assertEqual(self.client(candidate).get(path + "?q=张三").status_code, 403)

    def test_public_code_compression_preserves_content_and_conditional_requests(self):
        client = self.app.test_client()
        identity = client.get("/vendor/three.module.js", headers={"Accept-Encoding": "identity"})
        compressed = client.get("/vendor/three.module.js", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(compressed.status_code, 200)
        self.assertEqual(compressed.headers["Content-Encoding"], "gzip")
        self.assertEqual(gzip.decompress(compressed.data), identity.data)
        self.assertLess(len(compressed.data), len(identity.data) / 3)
        self.assertIn("Accept-Encoding", compressed.headers["Vary"])
        cached = client.get("/vendor/three.module.js", headers={"Accept-Encoding": "gzip", "If-None-Match": compressed.headers["ETag"]})
        self.assertEqual(cached.status_code, 304)
        self.assertNotIn("Content-Encoding", client.get("/vendor/three.module.js", headers={"Accept-Encoding": "gzip;q=0"}).headers)
        self.assertNotIn("Content-Encoding", client.get("/api/me", headers={"Accept-Encoding": "gzip"}).headers)
        self.assertNotIn("Content-Encoding", client.get("/welcome.html", headers={"Accept-Encoding": "gzip"}).headers)
        self.assertEqual(client.get("/js/../../config.yaml").status_code, 404)
