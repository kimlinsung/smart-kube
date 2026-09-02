from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from backend import db
from backend.app import create_app


class AuditMigrationTest(unittest.TestCase):
    def test_legacy_audit_rows_survive_source_ip_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_db_path = db.DB_PATH
            db.DB_PATH = os.path.join(temp_dir, "legacy.db")
            try:
                connection = sqlite3.connect(db.DB_PATH)
                connection.execute(
                    "CREATE TABLE audit_logs ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, "
                    "action TEXT, detail TEXT, created_at INTEGER)"
                )
                connection.execute(
                    "INSERT INTO audit_logs(user_id, username, action, detail, created_at) "
                    "VALUES(1, 'legacy-user', 'login', '', 123456)"
                )
                connection.commit()
                connection.close()

                db.init_db()

                with db.cursor() as cur:
                    cur.execute("PRAGMA table_info(audit_logs)")
                    columns = {row["name"] for row in cur.fetchall()}
                    cur.execute("SELECT * FROM audit_logs WHERE username='legacy-user'")
                    row = dict(cur.fetchone())
                self.assertIn("source_ip", columns)
                self.assertEqual(row["created_at"], 123456)
                self.assertEqual(row["action"], "login")
                self.assertIsNone(row["source_ip"])
            finally:
                db.DB_PATH = old_db_path


class AuditVisitTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, "test.db")
        with mock.patch("backend.k8s_client.ensure_namespace"), mock.patch(
            "backend.k8s_client.migrate_unlabeled_pods_to", return_value=0
        ):
            self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def tearDown(self):
        db.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def latest_log(self):
        with db.cursor() as cur:
            cur.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 1")
            return dict(cur.fetchone())

    def test_anonymous_page_visit_records_proxy_ip(self):
        response = self.client.get(
            "/welcome.html",
            headers={"X-Real-IP": "203.0.113.42"},
        )

        self.assertEqual(response.status_code, 200)
        log = self.latest_log()
        self.assertIsNone(log["user_id"])
        self.assertEqual(log["username"], "unknown")
        self.assertEqual(log["action"], "page_view")
        self.assertEqual(log["detail"], "/welcome.html")
        self.assertEqual(log["source_ip"], "203.0.113.42")
        response.close()

    def test_direct_client_cannot_spoof_forwarded_ip(self):
        response = self.client.get(
            "/devices.html",
            headers={"X-Real-IP": "203.0.113.99"},
            environ_base={"REMOTE_ADDR": "198.51.100.7"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.latest_log()["source_ip"], "198.51.100.7")
        response.close()

    def test_static_asset_does_not_create_visit_log(self):
        response = self.client.get("/css/style.css")

        self.assertEqual(response.status_code, 200)
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM audit_logs")
            self.assertEqual(cur.fetchone()["count"], 0)
        response.close()


if __name__ == "__main__":
    unittest.main()
