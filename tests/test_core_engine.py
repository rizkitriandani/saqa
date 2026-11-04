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
        # Narasi bebas yang tidak dapat dikompilasi menjadi asersi mesin wajib ditolak
        raw_rules = [
            "url does not contain \"/login\"",
            "Sistem harus berjalan dengan cepat dan tanpa hambatan sama sekali" # Tidak terukur / tidak didukung
        ]
        compiled, unparseable = compile_expected_results(raw_rules)
        self.assertEqual(len(compiled), 1)
        self.assertEqual(len(unparseable), 1)
        self.assertIn("Sistem harus berjalan", unparseable[0])

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

if __name__ == "__main__":
    unittest.main()
