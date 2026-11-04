import os
import sys
import json
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from runner.diagnostics import get_failure_context, attach_ai_diagnosis
import docx as docx_pkg

class TestDiagnostics(unittest.TestCase):

    def test_get_failure_context_identifies_failure_screenshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = Path(tmpdir)
            run_dir = proj_dir / "artifacts" / "RUN_FAIL_01"
            run_dir.mkdir(parents=True)
            meta_path = run_dir / "metadata.json"

            sample_meta = {
                "run_id": "RUN_FAIL_01",
                "test_case_id": "TC-001",
                "title": "Failed Login",
                "verdict": "FAILED",
                "target_url": "https://example.com/login",
                "actual_result": "Kriteria hasil tidak terpenuhi",
                "error_message": "Assertion failed",
                "steps": [
                    {"step_number": "1", "action": "navigate", "status": "COMPLETED", "notes": "Loaded"},
                    {"step_number": "2", "action": "click", "status": "FAILED", "notes": "Failed"}
                ],
                "artifacts": {
                    "screenshots": [
                        str(run_dir / "screenshots" / "01_step.png"),
                        str(run_dir / "screenshots" / "error_state.png")
                    ]
                }
            }
            meta_path.write_text(json.dumps(sample_meta), encoding="utf-8")

            # Tambahkan snapshot
            (run_dir / "test-case-snapshot.md").write_text("# Snapshot Content", encoding="utf-8")

            ctx = get_failure_context("RUN_FAIL_01", project_root=proj_dir)
            self.assertEqual(ctx["run_id"], "RUN_FAIL_01")
            self.assertEqual(ctx["verdict"], "FAILED")
            self.assertEqual(ctx["test_case_id"], "TC-001")
            self.assertIn("error_state.png", ctx["failure_screenshot_path"])
            self.assertIn("# Snapshot Content", ctx["test_case_snapshot"])

    def test_attach_ai_diagnosis_updates_metadata_and_docx(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = Path(tmpdir)
            run_dir = proj_dir / "artifacts" / "RUN_DIAG_02"
            run_dir.mkdir(parents=True)
            meta_path = run_dir / "metadata.json"

            sample_meta = {
                "run_id": "RUN_DIAG_02",
                "test_case_id": "TC-002",
                "title": "Diagnosis Test",
                "verdict": "FAILED",
                "target_url": "https://example.com/form",
                "actual_result": "Form tidak dapat disubmit",
                "steps": []
            }
            meta_path.write_text(json.dumps(sample_meta), encoding="utf-8")

            diagnosis = "Akar Masalah: Tombol Submit disabled karena field NIK kurang dari 16 digit."
            res = attach_ai_diagnosis("RUN_DIAG_02", diagnosis, project_root=proj_dir)

            self.assertEqual(res["run_id"], "RUN_DIAG_02")
            self.assertEqual(res["ai_diagnosis"], diagnosis)

            # Verifikasi metadata tersimpan
            with open(meta_path) as f:
                saved = json.load(f)
            self.assertEqual(saved["ai_diagnosis"], diagnosis)

            # Verifikasi file docx terupdate dengan teks diagnosis
            docx_file = proj_dir / res["report_docx"]
            self.assertTrue(docx_file.exists())
            doc = docx_pkg.Document(docx_file)
            xml_text = doc._element.xml
            self.assertIn("Analisis Akar Masalah AI", xml_text)
            self.assertIn("field NIK kurang dari 16 digit", xml_text)

    def test_cli_diagnose_helper(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = Path(tmpdir)
            run_dir = proj_dir / "artifacts" / "RUN_CLI_DIAG"
            run_dir.mkdir(parents=True)
            meta_path = run_dir / "metadata.json"
            meta_path.write_text(json.dumps({
                "run_id": "RUN_CLI_DIAG",
                "test_case_id": "TC-003",
                "title": "CLI Diagnosis",
                "verdict": "BLOCKED",
                "actual_result": "Akun terkunci"
            }), encoding="utf-8")

            from cli import cmd_diagnose
            import argparse

            # 1. Inspect without attach
            args_inspect = argparse.Namespace(run_id="RUN_CLI_DIAG", attach=None, project_root=str(proj_dir))
            ret_inspect = cmd_diagnose(args_inspect)
            self.assertEqual(ret_inspect, 0)

            # 2. Attach diagnosis
            args_attach = argparse.Namespace(
                run_id="RUN_CLI_DIAG",
                attach="Analisis: Staging terkena rate-limiting 9 menit.",
                project_root=str(proj_dir)
            )
            ret_attach = cmd_diagnose(args_attach)
            self.assertEqual(ret_attach, 0)

            with open(meta_path) as f:
                saved = json.load(f)
            self.assertIn("rate-limiting 9 menit", saved["ai_diagnosis"])

if __name__ == "__main__":
    unittest.main()
