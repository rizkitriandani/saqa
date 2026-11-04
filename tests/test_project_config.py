import os
import sys
import json
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from runner.config import (
    load_project_env,
    load_project_config,
    validate_project_config,
    create_project_config,
    SUPPORTED_CONFIG_VERSION
)

class TestProjectConfig(unittest.TestCase):

    def test_project_env_and_config_isolation(self):
        # Memastikan Proyek A dan Proyek B memiliki konfigurasi dan environment terisolasi
        with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
            path_a = Path(tmp_a)
            path_b = Path(tmp_b)

            # Setup Project A
            create_project_config(path_a, "project-alpha", "https://alpha.example.com", enable_google_drive=False)
            (path_a / ".env").write_text("QA_USERNAME=user_alpha\nQA_PASSWORD=pass_alpha\n", encoding="utf-8")

            # Setup Project B
            create_project_config(path_b, "project-beta", "https://beta.example.com", enable_google_drive=True)
            (path_b / ".env").write_text("QA_USERNAME=user_beta\nQA_PASSWORD=pass_beta\n", encoding="utf-8")

            cfg_a = load_project_config(path_a)
            cfg_b = load_project_config(path_b)
            env_a = load_project_env(path_a)
            env_b = load_project_env(path_b)

            # Verifikasi ID & URL berbeda
            self.assertEqual(cfg_a["project_id"], "project-alpha")
            self.assertEqual(cfg_b["project_id"], "project-beta")
            self.assertEqual(cfg_a["environment"]["base_url"], "https://alpha.example.com")
            self.assertEqual(cfg_b["environment"]["base_url"], "https://beta.example.com")

            # Verifikasi output sink berbeda
            self.assertEqual([o["type"] for o in cfg_a["outputs"]], ["local"])
            self.assertIn("google_drive", [o["type"] for o in cfg_b["outputs"]])

            # Verifikasi environment terisolasi (tidak saling tumpang tindih)
            self.assertEqual(env_a["QA_USERNAME"], "user_alpha")
            self.assertEqual(env_b["QA_USERNAME"], "user_beta")
            self.assertNotEqual(env_a["QA_USERNAME"], env_b["QA_USERNAME"])

    def test_unsupported_input_source_rejected_fail_closed(self):
        invalid_cfg = {
            "version": 1,
            "project_id": "proj-jira",
            "environment": {"base_url": "https://example.com"},
            "input": {"source": "jira_webhook"}, # Belum didukung
            "outputs": [{"type": "local"}]
        }
        errors = validate_project_config(invalid_cfg)
        self.assertTrue(any("jira_webhook" in e for e in errors))

    def test_unsupported_output_sink_rejected_fail_closed(self):
        invalid_cfg = {
            "version": 1,
            "project_id": "proj-slack-out",
            "environment": {"base_url": "https://example.com"},
            "input": {"source": "repo"},
            "outputs": [{"type": "slack_webhook"}] # Belum didukung
        }
        errors = validate_project_config(invalid_cfg)
        self.assertTrue(any("slack_webhook" in e for e in errors))

    def test_create_project_config_no_overwrite_safety(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            create_project_config(tmppath, "proj-safe", "https://safe.example.com")

            # Mencoba membuat ulang tanpa overwrite wajib gagal
            with self.assertRaises(FileExistsError):
                create_project_config(tmppath, "proj-safe", "https://safe.example.com", overwrite=False)

    def test_no_secrets_in_generated_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            cfg_path = create_project_config(tmppath, "proj-clean", "https://clean.example.com", enable_google_drive=True)
            cfg_text = cfg_path.read_text(encoding="utf-8")
            example_text = (tmppath / ".env.example").read_text(encoding="utf-8")

            # Memastikan saqa.json tidak memuat kata sandi atau kredensial rahasia
            self.assertNotIn("password_value", cfg_text.lower())
            self.assertNotIn("Dawaipagi", cfg_text)
            self.assertIn("your_password_here", example_text)

    def test_cli_config_approve_run_end_to_end(self):
        # Menguji alur lengkap CLI (config -> approve -> run) dari project root independen
        import subprocess
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_path = Path(tmpdir)
            
            # 1. cli config
            res_cfg = subprocess.run(
                ["python3", str(repo_root / "cli.py"), "config", "--project-root", str(proj_path), "--project-id", "test-proj", "--base-url", "http://localhost:3000"],
                capture_output=True, text=True
            )
            self.assertEqual(res_cfg.returncode, 0)
            self.assertTrue((proj_path / "saqa.json").exists())
            self.assertTrue((proj_path / ".env.example").exists())

            # 2. Setup test case & local html
            (proj_path / ".env").write_text("DEV_BASE_URL=http://localhost:3000\nQA_USERNAME=foo\nQA_PASSWORD=bar\n", encoding="utf-8")
            tc_dir = proj_path / "test-cases"
            tc_dir.mkdir(parents=True)
            tc_file = tc_dir / "TC-001.md"
            html_file = proj_path / "index.html"
            html_file.write_text("<html><body><h1>Hello Test Proj</h1></body></html>", encoding="utf-8")
            file_url = f"file://{html_file.resolve()}"

            tc_file.write_text(
                f"# TC-001: Sample\n\n"
                f"- **ID**: TC-001\n"
                f"- **Title**: Sample\n"
                f"- **Type**: Positive\n"
                f"- **Execution Mode**: deterministic\n"
                f"- **Approval Status**: pending\n"
                f"- **Target URL**: {file_url}\n\n"
                f"## Test Steps\n"
                f"| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
                f"| :--- | :--- | :--- | :--- | :--- |\n"
                f"| 1 | navigate | {file_url} | - | Loaded |\n\n"
                f"## Expected Results\n"
                f"- heading contains \"Hello Test Proj\"\n",
                encoding="utf-8"
            )

            # 3. cli approve
            res_app = subprocess.run(
                ["python3", str(repo_root / "cli.py"), "approve", "test-cases/TC-001.md", "--project-root", str(proj_path)],
                capture_output=True, text=True
            )
            self.assertEqual(res_app.returncode, 0)
            self.assertIn("Approval Hash", tc_file.read_text(encoding="utf-8"))

            # 4. cli run
            res_run = subprocess.run(
                ["python3", str(repo_root / "cli.py"), "run", "test-cases/TC-001.md", "--project-root", str(proj_path), "--no-publish"],
                capture_output=True, text=True
            )
            self.assertEqual(res_run.returncode, 0)
            self.assertIn("Verdict: PASSED", res_run.stdout)
            self.assertIn("test-proj", res_run.stdout)

if __name__ == "__main__":
    unittest.main()
