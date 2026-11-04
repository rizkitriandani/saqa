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
            {"issue_key": "XYZ-999", "status": "In Testing", "event_id": "evt_allowlist_01"},
            headers={"X-Webhook-Secret": "super_secret_token_123"}
        )
        self.assertEqual(status, 403)
        self.assertIn("di luar allowlist", body.get("error", ""))

    def test_missing_event_id_rejected_400(self):
        # Request tanpa event_id wajib ditolak 400
        status, body = self._post(
            "/jira-webhook",
            {"issue_key": "MED-101", "status": "In Testing"},
            headers={"X-Webhook-Secret": "super_secret_token_123"}
        )
        self.assertEqual(status, 400)
        self.assertIn("event_id", body.get("error", ""))

    def test_missing_status_when_trigger_statuses_configured_rejected_400(self):
        # Request tanpa status saat trigger_statuses dikonfigurasi wajib ditolak 400
        status, body = self._post(
            "/jira-webhook",
            {"issue_key": "MED-101", "event_id": "evt_no_status"},
            headers={"X-Webhook-Secret": "super_secret_token_123"}
        )
        self.assertEqual(status, 400)
        self.assertIn("Status tiket tidak ditemukan", body.get("error", ""))

    def test_status_filter_skips_unmatched_status(self):
        # Status 'Backlog' tidak ada di trigger_statuses ['In Testing', 'In QA']
        status, body = self._post(
            "/jira-webhook",
            {"issue_key": "MED-101", "status": "Backlog", "event_id": "evt_skip_01"},
            headers={"X-Webhook-Secret": "super_secret_token_123"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "skipped")
        self.assertIn("Backlog", body["reason"])

    def test_local_runner_dispatch_accepted(self):
        status, body = self._post(
            "/jira-webhook",
            {"issue_key": "MED-101", "status": "In Testing", "event_id": "evt_local_01"},
            headers={"X-Webhook-Secret": "super_secret_token_123"}
        )
        self.assertEqual(status, 202)
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(body["runner"], "local")
        self.assertIn("job_id", body)

    def test_duplicate_event_id_detected_and_skipped(self):
        # Mengirim event_id yang sama persis kedua kalinya wajib diskip secara idempoten
        p = {"issue_key": "MED-102", "status": "In Testing", "event_id": "evt_dedup_01"}
        s1, b1 = self._post("/jira-webhook", p, headers={"X-Webhook-Secret": "super_secret_token_123"})
        self.assertEqual(s1, 202)

        s2, b2 = self._post("/jira-webhook", p, headers={"X-Webhook-Secret": "super_secret_token_123"})
        self.assertEqual(s2, 200)
        self.assertEqual(b2["status"], "duplicate_event")
        self.assertEqual(b2["event_id"], "evt_dedup_01")

    def test_github_runner_dispatch_accepted(self, mock_dispatch=None):
        # Set runner override ke github pada handler server
        self.handler_class.runner_override = "github"
        try:
            status, body = self._post(
                "/jira-webhook",
                {"issue_key": "MED-201", "status": "In Testing", "event_id": "evt_gh_01"},
                headers={"X-Webhook-Secret": "super_secret_token_123"}
            )
            self.assertEqual(status, 202)
            self.assertEqual(body["status"], "accepted")
            self.assertEqual(body["runner"], "github")
        finally:
            self.handler_class.runner_override = None

    def test_gitlab_runner_dispatch_accepted(self, mock_dispatch=None):
        # Set runner override ke gitlab pada handler server
        self.handler_class.runner_override = "gitlab"
        try:
            status, body = self._post(
                "/jira-webhook",
                {"issue_key": "MED-301", "status": "In Testing", "event_id": "evt_gl_01"},
                headers={"X-Webhook-Secret": "super_secret_token_123"}
            )
            self.assertEqual(status, 202)
            self.assertEqual(body["status"], "accepted")
            self.assertEqual(body["runner"], "gitlab")
        finally:
            self.handler_class.runner_override = None

    def test_oversized_payload_rejected_413(self):
        # Payload melebihi MAX_PAYLOAD_SIZE (1MB) wajib ditolak dengan 413
        oversized_str = "x" * (1024 * 1024 + 50)
        p = {"issue_key": "MED-103", "blob": oversized_str}
        try:
            status, body = self._post("/jira-webhook", p, headers={"X-Webhook-Secret": "super_secret_token_123"})
            self.assertEqual(status, 413)
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 413)
        except urllib.error.URLError as e:
            # Sisi server menutup koneksi setelah menerima header > 1MB
            self.assertTrue("Broken pipe" in str(e) or "Connection reset" in str(e))

    def test_job_queue_atomic_claim_and_status_transitions(self):
        from runner.adapters.job_queue import (
            get_db_path,
            enqueue_job,
            claim_next_pending_job,
            mark_job_status,
            reconcile_interrupted_jobs_on_startup
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_root = Path(tmpdir)
            db_path = get_db_path(proj_root)

            # 1. Enqueue 2 jobs
            job1_id, dup1 = enqueue_job(db_path, "proj-q", "evt_1", "MED-1", "local")
            job2_id, dup2 = enqueue_job(db_path, "proj-q", "evt_2", "MED-2", "local")
            self.assertFalse(dup1)
            self.assertFalse(dup2)

            # 2. Klaim atomik job 1 -> status otomatis menjadi RUNNING
            claimed1 = claim_next_pending_job(db_path, "proj-q")
            self.assertIsNotNone(claimed1)
            self.assertEqual(claimed1["id"], job1_id)
            self.assertEqual(claimed1["issue_key"], "MED-1")

            # 3. Klaim atomik job 2 -> status otomatis menjadi RUNNING
            claimed2 = claim_next_pending_job(db_path, "proj-q")
            self.assertIsNotNone(claimed2)
            self.assertEqual(claimed2["id"], job2_id)

            # 4. Antrean kosong -> return None
            claimed3 = claim_next_pending_job(db_path, "proj-q")
            self.assertIsNone(claimed3)

            # 5. Selesaikan job 1
            mark_job_status(db_path, job1_id, "COMPLETED")

            # 6. Simulasikan crash/restart saat job 2 masih RUNNING -> reconcile wajib ubah ke NEEDS_RECONCILIATION
            reconcile_interrupted_jobs_on_startup(db_path, "proj-q")

            import sqlite3
            with sqlite3.connect(str(db_path)) as conn:
                cur = conn.cursor()
                cur.execute("SELECT status, error_message FROM webhook_jobs WHERE id = ?", (job2_id,))
                row = cur.fetchone()
                self.assertEqual(row[0], "NEEDS_RECONCILIATION")
                self.assertIn("Interrupted", row[1])

    def test_missing_secret_blocks_server_startup_fail_closed(self):
        from runner.adapters.webhook_server import start_webhook_server
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_proj = Path(tmpdir)
            # Tanpa file .env / tanpa WEBHOOK_SECRET -> startup wajib melempar ValueError
            with self.assertRaises(ValueError) as ctx:
                start_webhook_server(project_root=empty_proj, allow_unauthenticated=False)
            self.assertIn("WEBHOOK_SECRET wajib disetel", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
