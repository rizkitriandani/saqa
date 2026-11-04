import os
import sys
import json
import tempfile
import unittest
from unittest.mock import MagicMock
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from plugins.hermes import schemas, tools, register

class TestHermesPlugin(unittest.TestCase):

    def test_schemas_structure(self):
        schema_list = [
            schemas.SAQA_RUN,
            schemas.SAQA_APPROVE,
            schemas.SAQA_DIAGNOSE,
            schemas.SAQA_JIRA_INSPECT,
            schemas.SAQA_JIRA_PROCESS
        ]
        for s in schema_list:
            self.assertIn("name", s)
            self.assertIn("description", s)
            self.assertIn("parameters", s)
            self.assertEqual(s["parameters"]["type"], "object")
            self.assertIn("properties", s["parameters"])
            self.assertIn("required", s["parameters"])

    def test_tools_saqa_approve_handler(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = Path(tmpdir)
            tc_file = proj_dir / "TC-001.md"
            tc_file.write_text(
                "# TC-001: Sample Test\n\n"
                "- **ID**: TC-001\n"
                "- **Title**: Sample Test\n"
                "- **Type**: Positive\n"
                "- **Execution Mode**: deterministic\n"
                "- **Approval Status**: pending\n"
                "- **Target URL**: https://example.com\n\n"
                "## Test Steps\n"
                "| Step | Action | Target Element / Label | Input Value | Expected Step Outcome |\n"
                "| :--- | :--- | :--- | :--- | :--- |\n"
                "| 1 | navigate | https://example.com | - | Loaded |\n\n"
                "## Expected Results\n"
                "- heading contains \"Sample Test\"\n",
                encoding="utf-8"
            )

            # 1. Call handler
            resp_str = tools.saqa_approve({"test_case": "TC-001.md", "project_root": str(proj_dir)})
            res = json.loads(resp_str)
            self.assertTrue(res["ok"])
            self.assertEqual(res["test_case_id"], "TC-001")
            self.assertIn("approval_hash", res)

            # 2. Call handler with missing parameter
            bad_resp = json.loads(tools.saqa_approve({}))
            self.assertFalse(bad_resp["ok"])
            self.assertIn("required", bad_resp["error"])

    def test_tools_saqa_diagnose_handler(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = Path(tmpdir)
            run_dir = proj_dir / "artifacts" / "RUN_HERMES_01"
            run_dir.mkdir(parents=True)
            meta_path = run_dir / "metadata.json"
            meta_path.write_text(json.dumps({
                "run_id": "RUN_HERMES_01",
                "test_case_id": "TC-001",
                "verdict": "FAILED",
                "actual_result": "Kriteria hasil gagal"
            }), encoding="utf-8")

            # 1. Get failure context
            resp_str = tools.saqa_diagnose({"run_id": "RUN_HERMES_01", "project_root": str(proj_dir)})
            res = json.loads(resp_str)
            self.assertTrue(res["ok"])
            self.assertEqual(res["context"]["run_id"], "RUN_HERMES_01")
            self.assertEqual(res["context"]["verdict"], "FAILED")

            # 2. Attach diagnosis
            resp_att = json.loads(tools.saqa_diagnose({
                "run_id": "RUN_HERMES_01",
                "attach_analysis": "Analisis AI: Gagal karena validasi",
                "project_root": str(proj_dir)
            }))
            self.assertTrue(resp_att["ok"])
            self.assertTrue(resp_att["attached"])

    def test_handle_saqa_slash_command(self):
        # 1. Help
        help_out = tools.handle_saqa_command("help")
        self.assertIn("SAQA Commands in Hermes", help_out)

        # 2. Unknown subcommand
        bad_out = json.loads(tools.handle_saqa_command("unknown_xyz"))
        self.assertIn("error", bad_out)

    def test_hermes_register_contract(self):
        mock_ctx = MagicMock()
        register(mock_ctx)

        # Harus mendaftarkan 7 tool
        self.assertEqual(mock_ctx.register_tool.call_count, 7)
        registered_names = [call[1]["name"] for call in mock_ctx.register_tool.call_args_list]
        self.assertIn("saqa_run", registered_names)
        self.assertIn("saqa_approve", registered_names)
        self.assertIn("saqa_approve_and_run", registered_names)
        self.assertIn("saqa_diagnose", registered_names)
        self.assertIn("saqa_jira_inspect", registered_names)
        self.assertIn("saqa_jira_validate", registered_names)
        self.assertIn("saqa_jira_process", registered_names)

        # Harus mendaftarkan slash command /saqa
        mock_ctx.register_command.assert_called_once()
        self.assertEqual(mock_ctx.register_command.call_args[0][0], "saqa")

if __name__ == "__main__":
    unittest.main()
