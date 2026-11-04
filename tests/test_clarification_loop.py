import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from runner.readiness import (
    evaluate_ticket_readiness,
    ReasonCode,
    ActionRequired,
    create_or_get_clarification_session,
    init_clarification_db,
    update_clarification_draft
)
from runner.adapters.notifier import (
    dispatch_clarification_prompt,
    dispatch_execution_result,
    send_telegram_message,
    send_slack_webhook,
    send_discord_webhook
)
from runner.parser import compute_canonical_content_hash

class TestClarificationLoop(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.proj_dir = Path(self.tmpdir.name)
        self.tc_dir = self.proj_dir / "test-cases"
        self.tc_dir.mkdir(parents=True)
        self.db_path = self.proj_dir / "artifacts" / "saqa_jobs.db"
        (self.proj_dir / "artifacts").mkdir(parents=True)

        # Setup base test case TC-001 approved
        tc_content = (
            "# TC-001: Sample Test\n\n"
            "- **ID**: TC-001\n"
            "- **Title**: Sample Test\n"
            "- **Type**: Positive\n"
            "- **Execution Mode**: deterministic\n"
            "- **Approval Status**: approved\n"
            "- **Target URL**: https://example.com\n\n"
            "## Test Steps\n"
            "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
            "| 1 | navigate | https://example.com | - | Loaded |\n\n"
            "## Expected Results\n"
            "- heading contains \"Sample\"\n"
        )
        h = compute_canonical_content_hash(tc_content)
        tc_signed = tc_content.replace(
            "- **Approval Status**: approved",
            f"- **Approval Status**: approved\n- **Approval Hash**: {h}"
        )
        (self.tc_dir / "TC-001-sample.md").write_text(tc_signed, encoding="utf-8")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_evaluate_ticket_readiness_ready(self):
        desc = "h3. Test Cases\n- TC-001"
        res = evaluate_ticket_readiness(desc, self.proj_dir)
        self.assertTrue(res["ready"])
        self.assertEqual(res["reason_code"], ReasonCode.READY)
        self.assertEqual(res["action_required"], ActionRequired.RUN)
        self.assertEqual(len(res["test_case_paths"]), 1)

    def test_evaluate_ticket_readiness_missing_reference(self):
        desc = "Deskripsi tiket biasa tanpa referensi test case atau skenario."
        res = evaluate_ticket_readiness(desc, self.proj_dir)
        self.assertFalse(res["ready"])
        self.assertEqual(res["reason_code"], ReasonCode.MISSING_TEST_CASE_REFERENCE)
        self.assertEqual(res["action_required"], ActionRequired.INITIATE_CLARIFICATION)

    def test_evaluate_ticket_readiness_raw_scenario_detected(self):
        desc = (
            "Fitur tambah pasien baru.\n\n"
            "h3. QA Scenario\n"
            "- Preconditions: Buka form pendaftaran\n"
            "- Steps: Isi nama dan klik simpan\n"
            "- Expected: Muncul popup konfirmasi sukses\n"
        )
        res = evaluate_ticket_readiness(desc, self.proj_dir)
        self.assertFalse(res["ready"])
        self.assertEqual(res["reason_code"], ReasonCode.RAW_SCENARIO_DETECTED)
        self.assertEqual(res["action_required"], ActionRequired.INITIATE_CLARIFICATION)
        self.assertIsNotNone(res["raw_scenario"])
        self.assertIn("Isi nama dan klik simpan", res["raw_scenario"])

    def test_evaluate_ticket_readiness_test_case_unapproved(self):
        # Buat TC-002 dengan status pending
        tc2_content = (
            "# TC-002: Unapproved Case\n\n"
            "- **ID**: TC-002\n"
            "- **Title**: Unapproved\n"
            "- **Type**: Positive\n"
            "- **Execution Mode**: deterministic\n"
            "- **Approval Status**: pending\n"
            "- **Target URL**: https://example.com\n\n"
            "## Test Steps\n"
            "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
            "| 1 | navigate | https://example.com | - | Loaded |\n\n"
            "## Expected Results\n"
            "- heading contains \"Sample\"\n"
        )
        (self.tc_dir / "TC-002-unapproved.md").write_text(tc2_content, encoding="utf-8")

        desc = "h3. Test Cases\n- TC-002"
        res = evaluate_ticket_readiness(desc, self.proj_dir)
        self.assertFalse(res["ready"])
        self.assertEqual(res["reason_code"], ReasonCode.TEST_CASE_NOT_APPROVED)
        self.assertEqual(res["action_required"], ActionRequired.WAIT_APPROVAL)
        self.assertEqual(len(res["unapproved_files"]), 1)

    def test_clarification_session_persistence_and_deduplication(self):
        s1 = create_or_get_clarification_session(
            self.db_path,
            project_id="p1",
            issue_key="MED-130",
            raw_scenario="Login staff test",
            channel="telegram",
            channel_target="123456"
        )
        self.assertEqual(s1["issue_key"], "MED-130")
        self.assertEqual(s1["status"], "PENDING_CLARIFICATION")

        # Panggilan kedua untuk tiket yang sama harus mengembalikan sesi yang sama
        s2 = create_or_get_clarification_session(
            self.db_path,
            project_id="p1",
            issue_key="MED-130"
        )
        self.assertEqual(s1["id"], s2["id"])
        self.assertEqual(s1["session_id"], s2["session_id"])

        # Update draft
        update_clarification_draft(self.db_path, s1["session_id"], "test-cases/drafts/MED-130.md", "hash_abc_123")
        s3 = create_or_get_clarification_session(self.db_path, project_id="p1", issue_key="MED-130")
        self.assertEqual(s3["status"], "DRAFTED")
        self.assertEqual(s3["draft_path"], "test-cases/drafts/MED-130.md")

    @patch("runner.adapters.notifier._send_http_json")
    def test_notifier_dispatchers_telegram_slack_discord(self, mock_http):
        mock_http.return_value = True

        # 1. Telegram
        res_tg = send_telegram_message("tok123", "chat456", "Halo QA", thread_id="789")
        self.assertTrue(res_tg)
        sent_url, sent_payload = mock_http.call_args[0][0], mock_http.call_args[0][1]
        self.assertIn("api.telegram.org", sent_url)
        self.assertEqual(sent_payload["message_thread_id"], 789)

        # 2. Slack
        res_slack = send_slack_webhook("https://hooks.slack.com/services/xxx", "Pesan Slack", thread_ts="123.456")
        self.assertTrue(res_slack)
        sent_url, sent_payload = mock_http.call_args[0][0], mock_http.call_args[0][1]
        self.assertEqual(sent_payload["thread_ts"], "123.456")

        # 3. Discord
        res_discord = send_discord_webhook("https://discord.com/api/webhooks/xxx", "Pesan Discord")
        self.assertTrue(res_discord)
        sent_url, sent_payload = mock_http.call_args[0][0], mock_http.call_args[0][1]
        self.assertEqual(sent_payload["content"], "Pesan Discord")

    @patch("runner.adapters.jira.JiraClient.get_issue")
    def test_cmd_jira_validate_cli(self, mock_get_issue):
        # 1. Kasus Ready -> returncode 0
        mock_get_issue.return_value = {
            "key": "MED-101",
            "fields": {
                "summary": "Valid Ticket",
                "status": {"name": "In Testing"},
                "description": "h3. Test Cases\n- TC-001"
            }
        }
        (self.proj_dir / ".env").write_text("JIRA_BASE_URL=https://example.atlassian.net\nJIRA_EMAIL=a@b.com\nJIRA_API_TOKEN=tok\n", encoding="utf-8")
        from cli import cmd_jira_validate
        import argparse

        args = argparse.Namespace(issue_key="MED-101", project_root=str(self.proj_dir))
        ret_ready = cmd_jira_validate(args)
        self.assertEqual(ret_ready, 0)

        # 2. Kasus Unready -> returncode 1
        mock_get_issue.return_value = {
            "key": "MED-102",
            "fields": {
                "summary": "Empty Ticket",
                "status": {"name": "In Testing"},
                "description": "Deskripsi tanpa test case"
            }
        }
        args2 = argparse.Namespace(issue_key="MED-102", project_root=str(self.proj_dir))
        ret_unready = cmd_jira_validate(args2)
        self.assertEqual(ret_unready, 1)

    @patch("runner.adapters.jira.JiraClient.get_issue")
    @patch("runner.adapters.jira.JiraClient.post_comment")
    @patch("cli.dispatch_clarification_prompt")
    def test_cmd_jira_process_initiates_clarification_and_returns_2(self, mock_notify, mock_comment, mock_get_issue):
        # Tiket belum punya test case -> cmd_jira_process wajib return 2 (NEEDS_CLARIFICATION),
        # membuat draf di drafts/, dan mengirim notifikasi
        mock_get_issue.return_value = {
            "key": "MED-130",
            "fields": {
                "summary": "Feature without test cases",
                "status": {"name": "ON QA"},
                "description": "h3. QA Scenario\n- Langkah 1: Akses dev bcalife"
            }
        }
        (self.proj_dir / "saqa.json").write_text(json.dumps({
            "version": 1,
            "project_id": "proj-clarify",
            "environment": {"base_url": "https://example.com"},
            "input": {"source": "repo", "trigger_statuses": ["ON QA"]},
            "outputs": [{"type": "local"}]
        }), encoding="utf-8")
        (self.proj_dir / ".env").write_text(
            "JIRA_BASE_URL=https://example.atlassian.net\nJIRA_EMAIL=a@b.com\nJIRA_API_TOKEN=tok\n",
            encoding="utf-8"
        )

        from cli import cmd_jira_process
        import argparse
        args = argparse.Namespace(issue_key="MED-130", project_root=str(self.proj_dir), no_publish=False)
        ret = cmd_jira_process(args)

        self.assertEqual(ret, 2) # Sinyal returncode 2: NEEDS_CLARIFICATION
        mock_notify.assert_called_once()
        # Verifikasi file draf dibuat di drafts/
        draft_file = self.tc_dir / "drafts" / "MED-130-scenario.md"
        self.assertTrue(draft_file.exists())
        self.assertIn("Langkah 1: Akses dev bcalife", draft_file.read_text())

    def test_evaluate_ticket_readiness_inline_full_markdown(self):
        # Menguji jika deskripsi tiket Jira adalah dokumen Markdown lengkap
        # Keamanan: Meskipun teks yang ditempel memuat "approved" & hash, sistem tetap menolak auto-run (ready=False)
        # dan mewajibkan konfirmasi operator manusia (action_required=WAIT_APPROVAL).
        tc_text = (
            "# TC-001: Staff Login\n\n"
            "- **ID**: TC-001\n"
            "- **Title**: Staff Login Test\n"
            "- **Type**: Positive\n"
            "- **Execution Mode**: deterministic\n"
            "- **Approval Status**: approved\n"
            "- **Approval Hash**: dummy_hash_123\n"
            "- **Target URL**: https://example.com/login\n\n"
            "## Test Steps\n"
            "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
            "| 1 | navigate | https://example.com/login | - | Loaded |\n\n"
            "## Expected Results\n"
            "- url contains \"/dashboard\"\n"
        )

        res = evaluate_ticket_readiness(tc_text, self.proj_dir, issue_key="TRACKING-130")
        self.assertFalse(res["ready"])
        self.assertEqual(res["reason_code"], ReasonCode.INLINE_TEST_CASE_DETECTED)
        self.assertEqual(res["action_required"], ActionRequired.WAIT_APPROVAL)
        self.assertEqual(res["candidate_source_type"], "inline_markdown")
        self.assertIsNotNone(res["candidate_summary"])
        self.assertEqual(res["candidate_summary"]["id"], "TC-001")
        self.assertEqual(res["candidate_summary"]["steps_count"], 1)
        # Verifikasi evaluasi ini murni read-only (tidak menulis file ke disk)
        self.assertFalse((self.tc_dir / "inlined" / "TRACKING-130-TC-001.md").exists())

    def test_format_clarification_message_includes_three_options(self):
        from runner.adapters.notifier import format_clarification_message
        mock_readiness = {
            "reason_code": ReasonCode.TEST_CASE_NOT_APPROVED,
            "candidate_summary": {
                "id": "TC-001",
                "title": "Staff Authentication",
                "target_url": "https://dev.example.com",
                "steps_count": 4,
                "expected_results": ['heading contains "Dashboard"']
            }
        }
        mock_session = {"session_id": "clarify_123"}
        msg = format_clarification_message("MED-900", mock_readiness, mock_session)
        self.assertIn("MED-900", msg)
        self.assertIn("Staff Authentication", msg)
        self.assertIn("Approve & Run", msg)
        self.assertIn("Salin / tempel teks skenario baru", msg)
        self.assertIn("Lampirkan berkas", msg)

if __name__ == "__main__":
    unittest.main()
