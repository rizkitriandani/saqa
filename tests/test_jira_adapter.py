import os
import sys
import json
import base64
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import io

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from runner.adapters.jira import (
    JiraClient,
    extract_text_from_description,
    extract_test_case_references,
    extract_qa_scenario_block,
    format_jira_verdict_comment
)

class TestJiraAdapter(unittest.TestCase):

    def setUp(self):
        self.base_url = "https://medlinx.atlassian.net"
        self.email = "qa@medlinx.id"
        self.token = "dummy_api_token_12345"
        self.client = JiraClient(self.base_url, self.email, self.token)

    def test_jira_client_auth_header_format(self):
        expected_raw = f"{self.email}:{self.token}".encode("utf-8")
        expected_b64 = base64.b64encode(expected_raw).decode("utf-8")
        self.assertEqual(self.client.auth_header, f"Basic {expected_b64}")

    def test_adf_and_text_description_extraction(self):
        # 1. Test raw string
        raw_str = "h3. QA Scenario\nSteps to reproduce"
        self.assertEqual(extract_text_from_description(raw_str), raw_str)

        # 2. Test ADF JSON structure
        adf_doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": "QA Scenario"}]
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Akses halaman bcalife dan login."}]
                }
            ]
        }
        extracted = extract_text_from_description(adf_doc)
        self.assertIn("QA Scenario", extracted)
        self.assertIn("Akses halaman bcalife dan login", extracted)

    def test_extract_test_case_references_unique(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tc_dir = Path(tmpdir)
            (tc_dir / "TC-001-login-valid.md").write_text("# TC-001", encoding="utf-8")
            (tc_dir / "TC-002-login-view.md").write_text("# TC-002", encoding="utf-8")

            desc = "Mohon jalankan pengujian untuk tiket ini: TC-001 dan juga TC-002."
            refs = extract_test_case_references(desc, tc_dir)
            self.assertEqual(len(refs), 2)
            self.assertEqual(refs[0].name, "TC-001-login-valid.md")
            self.assertEqual(refs[1].name, "TC-002-login-view.md")

    def test_extract_test_case_references_ambiguous_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tc_dir = Path(tmpdir)
            # Dua file memiliki ID yang sama (ambigu)
            (tc_dir / "TC-001-login-v1.md").write_text("# TC-001 v1", encoding="utf-8")
            (tc_dir / "TC-001-login-v2.md").write_text("# TC-001 v2", encoding="utf-8")

            desc = "Test case: TC-001"
            with self.assertRaises(ValueError) as ctx:
                extract_test_case_references(desc, tc_dir)
            self.assertIn("Referensi ambigu", str(ctx.exception))

    def test_extract_test_case_references_missing_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tc_dir = Path(tmpdir)
            desc = "Test case: TC-999"
            with self.assertRaises(FileNotFoundError) as ctx:
                extract_test_case_references(desc, tc_dir)
            self.assertIn("tidak ditemukan", str(ctx.exception))

    def test_extract_qa_scenario_block(self):
        desc = (
            "Fitur baru registrasi pasien.\n\n"
            "h3. QA Scenario\n"
            "- Step 1: Buka form pendaftaran\n"
            "- Step 2: Isi nomor identitas\n"
            "- Expected: Muncul notifikasi sukses\n\n"
            "h3. Catatan Lain\n"
            "Data dummy disediakan di staging."
        )
        scenario = extract_qa_scenario_block(desc)
        self.assertIsNotNone(scenario)
        self.assertIn("Buka form pendaftaran", scenario)
        self.assertNotIn("Data dummy disediakan", scenario)

    @patch("urllib.request.OpenerDirector.open")
    def test_jira_client_get_issue_mocked(self, mock_open):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "key": "MED-101",
            "fields": {
                "summary": "Fix login validation",
                "description": "Test Cases: TC-001",
                "status": {"name": "In Testing"}
            }
        }).encode("utf-8")
        mock_open.return_value.__enter__.return_value = mock_resp

        issue = self.client.get_issue("MED-101")
        self.assertEqual(issue["key"], "MED-101")
        self.assertEqual(issue["fields"]["summary"], "Fix login validation")

    @patch("urllib.request.OpenerDirector.open")
    def test_jira_client_attach_file_multipart_mocked(self, mock_open):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([{"id": "10001", "filename": "report.docx"}]).encode("utf-8")
        mock_open.return_value.__enter__.return_value = mock_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            doc_file = Path(tmpdir) / "report.docx"
            doc_file.write_bytes(b"PK\x03\x04fake_docx")

            res = self.client.attach_file("MED-101", doc_file)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["filename"], "report.docx")

            # Verifikasi Request dikirim dengan header X-Atlassian-Token
            sent_req = mock_open.call_args[0][0]
            self.assertEqual(sent_req.get_header("X-atlassian-token"), "no-check")
            self.assertTrue(sent_req.get_header("Content-type").startswith("multipart/form-data"))

    @patch("urllib.request.OpenerDirector.open")
    def test_jira_client_post_comment_mocked(self, mock_open):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"id": "20001", "body": "Report PASSED"}).encode("utf-8")
        mock_open.return_value.__enter__.return_value = mock_resp

        res = self.client.post_comment("MED-101", "Report PASSED")
        self.assertEqual(res["id"], "20001")

        sent_req = mock_open.call_args[0][0]
        self.assertEqual(sent_req.get_header("Content-type"), "application/json")
        sent_body = json.loads(sent_req.data.decode("utf-8"))
        self.assertEqual(sent_body["body"], "Report PASSED")

    def test_format_jira_verdict_comment(self):
        sample_meta = {
            "test_case_id": "TC-001",
            "title": "Staff Authentication",
            "verdict": "PASSED",
            "execution_duration_seconds": 8.4,
            "actual_result": "Semua asersi sukses",
            "timestamp": "2026-11-04T10:00:00"
        }
        attachments = [{"filename": "report.docx"}, {"filename": "evidence.webm"}]
        drive_info = {
            "published": True,
            "google_doc_url": "https://docs.google.com/doc1",
            "google_video_url": "https://drive.google.com/vid1"
        }
        cmt = format_jira_verdict_comment(sample_meta, attachments, drive_info)
        self.assertIn("h3. [SAQA Execution Report] (/) *PASSED*", cmt)
        self.assertIn("report.docx", cmt)
        self.assertIn("evidence.webm", cmt)
        self.assertIn("https://docs.google.com/doc1", cmt)

    @patch("runner.adapters.jira.JiraClient.get_issue")
    def test_cli_jira_inspect_mocked(self, mock_get_issue):
        mock_get_issue.return_value = {
            "key": "MED-200",
            "fields": {
                "summary": "Sample Issue for Inspection",
                "status": {"name": "In Testing"},
                "description": "Test Cases: TC-001\n\nh3. QA Scenario\n- Step 1: Navigasi"
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = Path(tmpdir)
            (proj_dir / ".env").write_text(
                "JIRA_BASE_URL=https://medlinx.atlassian.net\nJIRA_EMAIL=tester@medlinx.id\nJIRA_API_TOKEN=fake_token\n",
                encoding="utf-8"
            )
            from cli import cmd_jira_inspect
            import argparse
            args = argparse.Namespace(issue_key="MED-200", project_root=str(proj_dir))
            ret = cmd_jira_inspect(args)
            self.assertEqual(ret, 0)

    @patch("runner.adapters.jira.JiraClient.get_issue")
    @patch("runner.adapters.jira.JiraClient.attach_file")
    @patch("runner.adapters.jira.JiraClient.post_comment")
    @patch("runner.engine.run_test_case")
    def test_cmd_jira_process_no_publish_skips_mutations(self, mock_run, mock_comment, mock_attach, mock_get_issue):
        mock_get_issue.return_value = {
            "key": "MED-300",
            "fields": {
                "summary": "Process test",
                "status": {"name": "In Testing"},
                "description": "Test Cases: TC-001"
            }
        }
        mock_run.return_value = {
            "run_id": "RUN_TEST_JIRA",
            "test_case_id": "TC-001",
            "title": "Sample",
            "verdict": "PASSED",
            "execution_duration_seconds": 1.0,
            "actual_result": "Success"
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = Path(tmpdir)
            (proj_dir / ".env").write_text(
                "JIRA_BASE_URL=https://medlinx.atlassian.net\nJIRA_EMAIL=t@medlinx.id\nJIRA_API_TOKEN=tok\n",
                encoding="utf-8"
            )
            tc_dir = proj_dir / "test-cases"
            tc_dir.mkdir(parents=True)
            (tc_dir / "TC-001-sample.md").write_text("# TC-001", encoding="utf-8")

            from cli import cmd_jira_process
            import argparse
            args = argparse.Namespace(issue_key="MED-300", project_root=str(proj_dir), no_publish=True)
            ret = cmd_jira_process(args)
            self.assertEqual(ret, 0)
            # Memastikan tidak ada pengunggahan attachment maupun komentar ke Jira saat flag --no-publish aktif
            mock_attach.assert_not_called()
            mock_comment.assert_not_called()

if __name__ == "__main__":
    unittest.main()
