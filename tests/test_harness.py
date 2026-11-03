import os
import sys
import json
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from reporter.docx_builder import build_docx_report
from reporter.publisher import publish_artifacts

class TestQAHarness(unittest.TestCase):

    def test_docx_generation_with_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            meta_path = tmppath / "metadata.json"
            
            sc_dir = tmppath / "screenshots"
            sc_dir.mkdir(parents=True)
            dummy_png = sc_dir / "step1.png"
            png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
            dummy_png.write_bytes(png_bytes)

            sample_meta = {
                "run_id": "TEST_RUN",
                "test_case_id": "TC-SAMPLE",
                "title": "Sample Test",
                "timestamp": "2026-11-03T12:00:00",
                "target_url": "https://example.com",
                "execution_duration_seconds": 1.25,
                "verdict": "PASSED",
                "actual_result": "Semua kriteria sukses",
                "steps": [
                    {
                        "step_number": 1,
                        "action": "Navigasi awal",
                        "status": "COMPLETED",
                        "screenshot": str(dummy_png.relative_to(repo_root)) if dummy_png.is_relative_to(repo_root) else str(dummy_png),
                        "notes": "Halaman awal termuat"
                    }
                ],
                "artifacts": {
                    "screenshots": [str(dummy_png)],
                    "video": None
                }
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(sample_meta, f)

            docx_file = build_docx_report(meta_path)
            self.assertTrue(docx_file.exists())
            self.assertGreater(docx_file.stat().st_size, 5000)

    def test_publisher_run_id_path_traversal_guard(self):
        res = publish_artifacts("../evil_path")
        self.assertFalse(res["published"])
        self.assertEqual(res["reason"], "INVALID_RUN_ID")

    def test_publisher_non_existent_run(self):
        res = publish_artifacts("NON_EXISTENT_RUN_12345")
        self.assertFalse(res["published"])
        self.assertEqual(res["reason"], "RUN_NOT_FOUND")

if __name__ == "__main__":
    unittest.main()
