import os
import sys
import json
import argparse
from pathlib import Path

# Add current directory to sys.path
repo_root = Path(__file__).resolve().parent
sys.path.insert(0, str(repo_root))

from runner.engine import run_test_case
from reporter.docx_builder import build_docx_report
from reporter.publisher import publish_artifacts

def cmd_run(args):
    test_case_file = args.test_case or "test-cases/TC-001-login-valid.md"
    print(f"\n🚀 [Hermes QA Runner] Memulai eksekusi Kasus Uji: {test_case_file}")
    
    meta = run_test_case(test_case_file)
    run_id = meta["run_id"]
    verdict = meta["verdict"]

    print(f"📊 Evaluasi Peramban Selesai:")
    print(f"   • Run ID: {run_id}")
    print(f"   • Verdict: {verdict}")
    print(f"   • Durasi: {meta.get('execution_duration_seconds')} detik")
    print(f"   • Keterangan: {meta.get('actual_result', meta.get('error_message'))}")

    # Build DOCX Laporan
    run_dir = repo_root / "artifacts" / run_id
    meta_path = run_dir / "metadata.json"
    docx_path = build_docx_report(meta_path)
    print(f"📄 Laporan DOCX berhasil dikompilasi: {docx_path.relative_to(repo_root)}")

    # Attempt Google Drive / Docs Publish
    pub_result = publish_artifacts(run_id)
    if pub_result.get("published"):
        print(f"✅ Publikasi Google Drive Sukses:")
        print(f"   • Google Docs: {pub_result.get('google_doc_url')}")
        print(f"   • Bukti Video: {pub_result.get('google_video_url')}")
    else:
        print(f"⚠️  Status Publikasi: {pub_result.get('status', 'UNPUBLISHED')}")
        print(f"   • {pub_result.get('message')}")
        print(f"   • Untuk mencoba publikasi ulang: python3 cli.py publish {run_id}")

    return 0 if verdict == "PASSED" else 1

def cmd_publish(args):
    run_id = args.run_id
    print(f"📤 Mencoba publikasi ulang artefak untuk Run ID: {run_id}")
    pub_result = publish_artifacts(run_id)
    print(json.dumps(pub_result, indent=2))
    return 0 if pub_result.get("published") else 1

def cmd_list(args):
    artifacts_dir = repo_root / "artifacts"
    if not artifacts_dir.exists():
        print("Belum ada riwayat pengujian.")
        return 0

    runs = sorted([d for d in artifacts_dir.iterdir() if d.is_dir()], reverse=True)
    print(f"\n📋 Daftar Riwayat Eksekusi ({len(runs)} run):")
    print(f"{'Run ID':<22} | {'Test Case':<10} | {'Verdict':<8} | {'Publish Status':<12}")
    print("-" * 65)

    for r in runs:
        meta_file = r / "metadata.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r") as f:
                    m = json.load(f)
                tc_id = m.get("test_case_id", "-")
                v = m.get("verdict", "-")
                pub = "PUBLISHED" if m.get("publish_status", {}).get("published") else "UNPUBLISHED"
                print(f"{r.name:<22} | {tc_id:<10} | {v:<8} | {pub:<12}")
            except Exception:
                print(f"{r.name:<22} | {'(corrupt)':<10} | {'-':<8} | {'-':<12}")
    return 0

def main():
    parser = argparse.ArgumentParser(description="Hermes AI QA Agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_run = subparsers.add_parser("run", help="Jalankan Kasus Uji")
    parser_run.add_argument("test_case", nargs="?", default="test-cases/TC-001-login-valid.md", help="Path file kasus uji markdown")
    parser_run.set_defaults(func=cmd_run)

    parser_pub = subparsers.add_parser("publish", help="Publikasikan artefak ke Google Drive")
    parser_pub.add_argument("run_id", help="ID Run yang akan dipublikasikan")
    parser_pub.set_defaults(func=cmd_publish)

    parser_list = subparsers.add_parser("list", help="Daftar riwayat eksekusi pengujian")
    parser_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
