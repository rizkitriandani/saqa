import os
import sys
import json
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from runner.parser import (
    parse_markdown_test_case,
    validate_test_case_contract,
    compute_canonical_content_hash,
    compile_expected_results,
    ALLOWED_ENV_VARS
)
from runner.engine import run_test_case

class TestCoreEngineHardening(unittest.TestCase):

    def test_ai_execution_mode_rejected_fail_closed(self):
        content = (
            "# TC-101: Test with AI Mode\n\n"
            "- **ID**: TC-101\n"
            "- **Title**: Test AI\n"
            "- **Type**: Positive\n"
            "- **Execution Mode**: ai\n"
            "- **Approval Status**: approved\n"
            "- **Target URL**: https://example.com\n\n"
            "## Test Steps\n"
            "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
            "| 1 | navigate | https://example.com | - | Loaded |\n\n"
            "## Expected Results\n"
            "- page contains \"Success\"\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tc_file = Path(tmpdir) / "tc_ai.md"
            tc_file.write_text(content, encoding="utf-8")
            parsed = parse_markdown_test_case(tc_file)
            errors = validate_test_case_contract(parsed)
            self.assertTrue(any("ai" in e.lower() for e in errors))

    def test_unsupported_expected_result_rejected_fail_closed(self):
        # Narasi bebas atau klausa gabungan yang tidak memenuhi grammar fullmatch wajib ditolak
        raw_rules = [
            'url does not contain "/login"',
            'url contains "/login" and balance equals "0"', # Adversarial: trailing clause
            'url contains /unquoted',                        # Adversarial: unquoted
            'url contains ""',                               # Adversarial: empty operand
            'heading contains "Unclosed quote',              # Adversarial: unclosed quote
            "Sistem harus berjalan dengan cepat dan lancar"   # Narasi bebas
        ]
        compiled, unparseable = compile_expected_results(raw_rules)
        self.assertEqual(len(compiled), 1)
        self.assertEqual(len(unparseable), 5)
        self.assertIn('url contains "/login" and balance equals "0"', unparseable)
        self.assertIn('url contains /unquoted', unparseable)
        self.assertIn('url contains ""', unparseable)
        self.assertIn('heading contains "Unclosed quote', unparseable)
        self.assertIn('Sistem harus berjalan dengan cepat dan lancar', unparseable)

    def test_supported_expected_results_compiled_cleanly(self):
        raw_rules = [
            "url does not contain \"/login\"",
            "url contains \"dashboard\"",
            "heading contains \"Dashboard\"",
            "text contains \"Super User\"",
            "element \"#btn-submit\" is visible"
        ]
        compiled, unparseable = compile_expected_results(raw_rules)
        self.assertEqual(unparseable, [])
        self.assertEqual(len(compiled), 5)
        types = [c["type"] for c in compiled]
        self.assertIn("url_not_contains", types)
        self.assertIn("url_contains", types)
        self.assertIn("heading_contains", types)
        self.assertIn("text_contains", types)
        self.assertIn("element_visible", types)

    def test_approval_hash_validation_and_drift_detection(self):
        content = (
            "# TC-202: Hash Test Case\n\n"
            "- **ID**: TC-202\n"
            "- **Title**: Hash Validation\n"
            "- **Type**: Positive\n"
            "- **Execution Mode**: deterministic\n"
            "- **Approval Status**: approved\n"
            "- **Target URL**: https://example.com\n\n"
            "## Test Steps\n"
            "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
            "| 1 | navigate | https://example.com | - | Loaded |\n\n"
            "## Expected Results\n"
            "- page contains \"Success\"\n"
        )
        h = compute_canonical_content_hash(content)
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 64) # SHA-256

        # Modifikasi konten (tambah spasi atau ubah teks) wajib menghasilkan hash berbeda
        tampered = content.replace("Success", "Tampered")
        h_tampered = compute_canonical_content_hash(tampered)
        self.assertNotEqual(h, h_tampered)

    def test_approval_hash_mismatch_blocks_execution(self):
        # Kasus uji dengan hash salah / kedaluwarsa wajib BLOCKED tanpa meluncurkan browser
        content = (
            "# TC-203: Drift Case\n\n"
            "- **ID**: TC-203\n"
            "- **Title**: Drift Test\n"
            "- **Type**: Positive\n"
            "- **Execution Mode**: deterministic\n"
            "- **Approval Status**: approved\n"
            "- **Approval Hash**: invalid_dummy_hash_value_1234567890\n"
            "- **Target URL**: https://example.com\n\n"
            "## Test Steps\n"
            "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
            "| 1 | navigate | https://example.com | - | Loaded |\n\n"
            "## Expected Results\n"
            "- page contains \"Success\"\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tc_file = Path(tmpdir) / "tc_drift.md"
            tc_file.write_text(content, encoding="utf-8")
            res = run_test_case(str(tc_file))
            self.assertEqual(res["verdict"], "BLOCKED")
            self.assertIn("Approval Hash tidak cocok", res["actual_result"])

    def test_variable_allowlist_security(self):
        # Hanya allowlist variabel yang diizinkan (DEV_BASE_URL, QA_USERNAME, QA_PASSWORD)
        self.assertIn("DEV_BASE_URL", ALLOWED_ENV_VARS)
        self.assertIn("QA_USERNAME", ALLOWED_ENV_VARS)
        self.assertIn("QA_PASSWORD", ALLOWED_ENV_VARS)
        self.assertNotIn("GOOGLE_APPLICATION_CREDENTIALS", ALLOWED_ENV_VARS)
        self.assertNotIn("GOOGLE_DRIVE_FOLDER_ID", ALLOWED_ENV_VARS)

    def test_offline_html_run_passed(self):
        # Menguji eksekusi deterministik dan asersi generik secara offline via fixture HTML
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            html_file = tmppath / "dashboard.html"
            html_file.write_text(
                "<!DOCTYPE html><html><head><title>Portal QA</title></head>"
                "<body><h1>Dashboard Utama</h1><p>Status: Aktif</p>"
                "<button id='action-btn'>Konfirmasi</button></body></html>",
                encoding="utf-8"
            )
            file_url = f"file://{html_file.resolve()}"

            tc_content = (
                "# TC-LOCAL-01: Offline Test\n\n"
                "- **ID**: TC-LOCAL-01\n"
                "- **Title**: Offline Test Case\n"
                "- **Type**: Positive\n"
                "- **Execution Mode**: deterministic\n"
                "- **Approval Status**: approved\n"
                f"- **Target URL**: {file_url}\n\n"
                "## Test Steps\n"
                "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
                "| :--- | :--- | :--- | :--- | :--- |\n"
                f"| 1 | navigate | {file_url} | - | Halaman termuat |\n"
                "| 2 | click | Konfirmasi | - | Tombol diklik |\n\n"
                "## Expected Results\n"
                "- heading contains \"Dashboard Utama\"\n"
                "- text contains \"Status: Aktif\"\n"
                "- element \"#action-btn\" is visible\n"
            )
            h = compute_canonical_content_hash(tc_content)
            tc_with_hash = tc_content.replace(
                "- **Approval Status**: approved",
                f"- **Approval Status**: approved\n- **Approval Hash**: {h}"
            )
            tc_path = tmppath / "tc_offline.md"
            tc_path.write_text(tc_with_hash, encoding="utf-8")

            res = run_test_case(str(tc_path))
            self.assertEqual(res["verdict"], "PASSED")
            self.assertIn("Semua 3 kriteria asersi berhasil divalidasi", res["actual_result"])

    def test_offline_html_run_failed_when_expectation_unmet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            html_file = tmppath / "page.html"
            html_file.write_text("<html><body><h1>Judul Lain</h1></body></html>", encoding="utf-8")
            file_url = f"file://{html_file.resolve()}"

            tc_content = (
                "# TC-LOCAL-02: Expectation Unmet\n\n"
                "- **ID**: TC-LOCAL-02\n"
                "- **Title**: Expectation Unmet Test\n"
                "- **Type**: Positive\n"
                "- **Execution Mode**: deterministic\n"
                "- **Approval Status**: approved\n"
                f"- **Target URL**: {file_url}\n\n"
                "## Test Steps\n"
                "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
                "| :--- | :--- | :--- | :--- | :--- |\n"
                f"| 1 | navigate | {file_url} | - | Halaman termuat |\n\n"
                "## Expected Results\n"
                "- heading contains \"Dashboard Utama\"\n"
            )
            h = compute_canonical_content_hash(tc_content)
            tc_with_hash = tc_content.replace(
                "- **Approval Status**: approved",
                f"- **Approval Status**: approved\n- **Approval Hash**: {h}"
            )
            tc_path = tmppath / "tc_unmet.md"
            tc_path.write_text(tc_with_hash, encoding="utf-8")

            res = run_test_case(str(tc_path))
            self.assertEqual(res["verdict"], "FAILED")
            self.assertIn("Heading tidak memuat 'Dashboard Utama'", res["actual_result"])

    def test_offline_html_ambiguous_target_rejected(self):
        # Dua tombol dengan teks sama persis tanpa id unik wajib melempar error ambiguitas
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            html_file = tmppath / "ambiguous.html"
            html_file.write_text(
                "<html><body><button>Submit</button><button>Submit</button></body></html>",
                encoding="utf-8"
            )
            file_url = f"file://{html_file.resolve()}"

            tc_content = (
                "# TC-LOCAL-03: Ambiguous Target\n\n"
                "- **ID**: TC-LOCAL-03\n"
                "- **Title**: Ambiguous Target Test\n"
                "- **Type**: Positive\n"
                "- **Execution Mode**: deterministic\n"
                "- **Approval Status**: approved\n"
                f"- **Target URL**: {file_url}\n\n"
                "## Test Steps\n"
                "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
                "| :--- | :--- | :--- | :--- | :--- |\n"
                f"| 1 | navigate | {file_url} | - | Halaman termuat |\n"
                "| 2 | click | Submit | - | Tombol diklik |\n\n"
                "## Expected Results\n"
                "- text contains \"Submit\"\n"
            )
            h = compute_canonical_content_hash(tc_content)
            tc_with_hash = tc_content.replace(
                "- **Approval Status**: approved",
                f"- **Approval Status**: approved\n- **Approval Hash**: {h}"
            )
            tc_path = tmppath / "tc_ambig.md"
            tc_path.write_text(tc_with_hash, encoding="utf-8")

            res = run_test_case(str(tc_path))
            self.assertEqual(res["verdict"], "ERROR")
            self.assertIn("Penargetan ambigu", res["error_message"])

    def test_inline_assert_step_failure_is_failed_not_error(self):
        # Kegagalan asersi langkah (bukan error sistem) wajib menghasilkan verdict FAILED
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            html_file = tmppath / "simple.html"
            html_file.write_text("<html><body><p>Hello World</p></body></html>", encoding="utf-8")
            file_url = f"file://{html_file.resolve()}"

            tc_content = (
                "# TC-LOCAL-04: Step Assert Fail\n\n"
                "- **ID**: TC-LOCAL-04\n"
                "- **Title**: Step Assert Fail Test\n"
                "- **Type**: Positive\n"
                "- **Execution Mode**: deterministic\n"
                "- **Approval Status**: approved\n"
                f"- **Target URL**: {file_url}\n\n"
                "## Test Steps\n"
                "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
                "| :--- | :--- | :--- | :--- | :--- |\n"
                f"| 1 | navigate | {file_url} | - | Termuat |\n"
                "| 2 | assert | Nonexistent Text | - | Asersi langkah gagal |\n\n"
                "## Expected Results\n"
                "- text contains \"Hello World\"\n"
            )
            h = compute_canonical_content_hash(tc_content)
            tc_with_hash = tc_content.replace(
                "- **Approval Status**: approved",
                f"- **Approval Status**: approved\n- **Approval Hash**: {h}"
            )
            tc_path = tmppath / "tc_assert_fail.md"
            tc_path.write_text(tc_with_hash, encoding="utf-8")

            res = run_test_case(str(tc_path))
            self.assertEqual(res["verdict"], "FAILED")
            self.assertIn("Kegagalan asersi langkah", res["actual_result"])

    def test_forbidden_origin_navigation_blocked(self):
        # Navigasi ke origin di luar allowlist wajib melempar PermissionError
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            tc_content = (
                "# TC-LOCAL-05: Forbidden Origin\n\n"
                "- **ID**: TC-LOCAL-05\n"
                "- **Title**: Forbidden Origin Test\n"
                "- **Type**: Positive\n"
                "- **Execution Mode**: deterministic\n"
                "- **Approval Status**: approved\n"
                "- **Target URL**: https://unauthorized-evil-site.com\n\n"
                "## Test Steps\n"
                "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
                "| :--- | :--- | :--- | :--- | :--- |\n"
                "| 1 | navigate | https://unauthorized-evil-site.com | - | Harusnya diblokir |\n\n"
                "## Expected Results\n"
                "- text contains \"anything\"\n"
            )
            h = compute_canonical_content_hash(tc_content)
            tc_with_hash = tc_content.replace(
                "- **Approval Status**: approved",
                f"- **Approval Status**: approved\n- **Approval Hash**: {h}"
            )
            tc_path = tmppath / "tc_evil.md"
            tc_path.write_text(tc_with_hash, encoding="utf-8")

            res = run_test_case(str(tc_path))
            self.assertEqual(res["verdict"], "ERROR")
            self.assertIn("diblokir oleh kebijakan keamanan", res["error_message"])

    def test_preflight_blocks_browser_launch_on_invalid_input(self):
        # Membuktikan secara deterministik bahwa browser TIDAK diluncurkan jika preflight gagal
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            tc_content = (
                "# TC-LOCAL-06: Preflight Fail\n\n"
                "- **ID**: TC-LOCAL-06\n"
                "- **Title**: Preflight Fail Test\n"
                "- **Type**: Positive\n"
                "- **Execution Mode**: deterministic\n"
                "- **Approval Status**: approved\n"
                "- **Target URL**: http://localhost/test\n\n"
                "## Test Steps\n"
                "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
                "| :--- | :--- | :--- | :--- | :--- |\n"
                "| 1 | navigate | http://localhost/test?pass=${QA_PASSWORD} | - | Password di URL terlarang |\n\n"
                "## Expected Results\n"
                "- text contains \"Hello\"\n"
            )
            h = compute_canonical_content_hash(tc_content)
            tc_with_hash = tc_content.replace(
                "- **Approval Status**: approved",
                f"- **Approval Status**: approved\n- **Approval Hash**: {h}"
            )
            tc_path = tmppath / "tc_preflight.md"
            tc_path.write_text(tc_with_hash, encoding="utf-8")

            with patch("runner.engine.sync_playwright") as mock_playwright:
                res = run_test_case(str(tc_path))
                self.assertEqual(res["verdict"], "ERROR")
                self.assertIn("Validasi preflight gagal (browser tidak dibuka)", res["error_message"])
                self.assertIn("QA_PASSWORD", res["error_message"])
                mock_playwright.assert_not_called()

if __name__ == "__main__":
    unittest.main()
