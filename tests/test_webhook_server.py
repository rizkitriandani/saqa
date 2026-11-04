import os
import sys
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock
from http.server import HTTPServer

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from runner.adapters.webhook_server import (
    SaqaWebhookHandler,
    extract_issue_key_from_payload,
    extract_status_from_payload
)

class TestWebhookServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.proj_dir = Path(cls.tmpdir.name)
        (cls.proj_dir / "saqa.json").write_text(json.dumps({
            "version": 1,
            "project_id": "test-webhook-proj",
            "environment": {
                "base_url": "https://staging.example.com",
                "project_keys": ["MED", "QA"]
            },
            "input": {
                "trigger": "jira_webhook",
                "trigger_statuses": ["In Testing", "In QA"]
            },
            "outputs": [{"type": "local"}]
        }), encoding="utf-8")

        (cls.proj_dir / ".env").write_text(
            "WEBHOOK_SECRET=super_secret_token_123\n"
            "GITHUB_REPO=user/repo\n"
            "GITHUB_PAT=fake_gh_pat\n"
            "GITLAB_PROJECT_ID=123456\n"
            "GITLAB_TRIGGER_TOKEN=fake_gl_token\n",
            encoding="utf-8"
        )

        class TestHandler(SaqaWebhookHandler):
            pass
        TestHandler.project_root = cls.proj_dir
        TestHandler.runner_override = None

        cls.handler_class = TestHandler
        cls.server = HTTPServer(("127.0.0.1", 0), TestHandler)
        cls.port = cls.server.server_port
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmpdir.cleanup()

    def _post(self, path: str, payload: dict, headers: dict = None) -> tuple:
        url = f"http://127.0.0.1:{self.port}{path}"
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return resp.status, body
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode("utf-8")) if e.fp else {}
            return e.code, body

    def _get(self, path: str) -> tuple:
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return resp.status, body
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode("utf-8")) if e.fp else {}
            return e.code, body

    def test_health_check_endpoint(self):
        status, body = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["project_id"], "test-webhook-proj")
        self.assertEqual(body["runner_target"], "local")

    def test_extract_issue_key_and_status_from_payloads(self):
        # 1. Custom Jira Automation data
        p1 = {"issue_key": "MED-101", "status": "In Testing"}
        self.assertEqual(extract_issue_key_from_payload(p1), "MED-101")
        self.assertEqual(extract_status_from_payload(p1), "In Testing")

        # 2. Native Jira webhook
        p2 = {
            "issue": {
                "key": "QA-202",
                "fields": {"status": {"name": "In QA"}}
            }
        }
        self.assertEqual(extract_issue_key_from_payload(p2), "QA-202")
        self.assertEqual(extract_status_from_payload(p2), "In QA")

    def test_secret_token_authentication_guard(self):
        # Tanpa secret -> 401
        status, body = self._post("/jira-webhook", {"issue_key": "MED-101"})
        self.assertEqual(status, 401)
        self.assertIn("Unauthorized", body.get("error", ""))

        # Dengan secret yang salah -> 401
        status, body = self._post("/jira-webhook", {"issue_key": "MED-101"}, headers={"X-Webhook-Secret": "wrong"})
        self.assertEqual(status, 401)

    def test_invalid_issue_key_rejected(self):
        status, body = self._post(
            "/jira-webhook",
            {"issue_key": "INVALID_KEY_123"},
            headers={"X-Webhook-Secret": "super_secret_token_123"}
        )
        self.assertEqual(status, 400)
        self.assertIn("tidak ditemukan atau formatnya tidak valid", body.get("error", ""))

    def test_project_key_allowlist_enforced(self):
        # Project key 'XYZ' di luar allowlist ['MED', 'QA'] -> 403 Forbidden
        status, body = self._post(
            "/jira-webhook",
            {"issue_key": "XYZ-999"},
            headers={"X-Webhook-Secret": "super_secret_token_123"}
        )
        self.assertEqual(status, 403)
        self.assertIn("di luar allowlist", body.get("error", ""))

    def test_status_filter_skips_unmatched_status(self):
        # Status 'Backlog' tidak ada di trigger_statuses ['In Testing', 'In QA']
        status, body = self._post(
            "/jira-webhook",
            {"issue_key": "MED-101", "status": "Backlog"},
            headers={"X-Webhook-Secret": "super_secret_token_123"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "skipped")
        self.assertIn("Backlog", body["reason"])

    @patch("runner.adapters.webhook_server.threading.Thread")
    def test_local_runner_dispatch_accepted(self, mock_thread):
        status, body = self._post(
            "/jira-webhook",
            {"issue_key": "MED-101", "status": "In Testing"},
            headers={"X-Webhook-Secret": "super_secret_token_123"}
        )
        self.assertEqual(status, 202)
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(body["runner"], "local")
        mock_thread.assert_called_once()

    @patch("runner.adapters.webhook_server.dispatch_github_actions")
    def test_github_runner_dispatch_accepted(self, mock_dispatch):
        mock_dispatch.return_value = {"status": "dispatched", "target": "github", "code": 204}

        # Set runner override ke github pada handler server
        self.handler_class.runner_override = "github"
        try:
            status, body = self._post(
                "/jira-webhook",
                {"issue_key": "MED-101", "status": "In Testing"},
                headers={"X-Webhook-Secret": "super_secret_token_123"}
            )
            self.assertEqual(status, 202)
            self.assertEqual(body["status"], "dispatched")
            self.assertEqual(body["runner"], "github")
            mock_dispatch.assert_called_once()
        finally:
            self.handler_class.runner_override = None

    @patch("runner.adapters.webhook_server.dispatch_gitlab_ci")
    def test_gitlab_runner_dispatch_accepted(self, mock_dispatch):
        mock_dispatch.return_value = {"status": "dispatched", "target": "gitlab", "code": 201}

        # Set runner override ke gitlab pada handler server
        self.handler_class.runner_override = "gitlab"
        try:
            status, body = self._post(
                "/jira-webhook",
                {"issue_key": "MED-101", "status": "In Testing"},
                headers={"X-Webhook-Secret": "super_secret_token_123"}
            )
            self.assertEqual(status, 202)
            self.assertEqual(body["status"], "dispatched")
            self.assertEqual(body["runner"], "gitlab")
            mock_dispatch.assert_called_once()
        finally:
            self.handler_class.runner_override = None

if __name__ == "__main__":
    unittest.main()
