import os
import sys
import json
import argparse
from pathlib import Path

# Add current directory to sys.path
repo_root = Path(__file__).resolve().parent
sys.path.insert(0, str(repo_root))

from runner.engine import run_test_case
from runner.parser import compute_canonical_content_hash, parse_markdown_test_case, validate_test_case_contract
from reporter.docx_builder import build_docx_report
from reporter.publisher import publish_artifacts

def cmd_approve(args):
    tc_path = repo_root / args.test_case if not os.path.isabs(args.test_case) else Path(args.test_case)
    if not tc_path.exists():
        print(f"❌ File kasus uji tidak ditemukan: {tc_path}")
        return 1

    content = tc_path.read_text(encoding="utf-8")
    parsed = parse_markdown_test_case(tc_path)
    errors = validate_test_case_contract(parsed)
    if errors:
        print(f"❌ Tidak dapat menyetujui kasus uji. Validasi kontrak gagal:")
        for e in errors:
            print(f"   • {e}")
        return 1

    canonical_hash = compute_canonical_content_hash(content)

    lines = content.splitlines()
    new_lines = []
    status_updated = False
    hash_updated = False

    for line in lines:
        if line.strip().startswith("- **Approval Status**:"):
            new_lines.append("- **Approval Status**: approved")
            status_updated = True
        elif line.strip().startswith("- **Approval Hash**:"):
            new_lines.append(f"- **Approval Hash**: {canonical_hash}")
            hash_updated = True
        else:
            new_lines.append(line)

    if not status_updated or not hash_updated:
        final_lines = []
        for line in new_lines:
            final_lines.append(line)
            if line.strip().startswith("- **Execution Mode**:") or line.strip().startswith("- **Type**:"):
                if not status_updated:
                    final_lines.append("- **Approval Status**: approved")
                    status_updated = True
                if not hash_updated:
                    final_lines.append(f"- **Approval Hash**: {canonical_hash}")
                    hash_updated = True
        new_lines = final_lines

    tc_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"✅ Kasus Uji berhasil disetujui (Approved):")
    print(f"   • File: {tc_path.relative_to(repo_root)}")
    print(f"   • ID: {parsed.get('id')}")
    print(f"   • Approval Hash: {canonical_hash}")
    return 0

def cmd_run(args):
    test_case_file = args.test_case or "test-cases/TC-001-login-valid.md"
    no_publish = getattr(args, "no_publish", False)
    print(f"\n🚀 [Hermes QA Runner] Memulai eksekusi Kasus Uji: {test_case_file}")
    
    meta = run_test_case(test_case_file)
    run_id = meta["run_id"]
    verdict = meta["verdict"]

    print(f"📊 Evaluasi Peramban Selesai:")
    print(f"   • Run ID: {run_id}")
    print(f"   • Verdict: {verdict}")
    print(f"   • Durasi: {meta.get('execution_duration_seconds')} detik")
    print(f"   • Keterangan: {meta.get('actual_result', meta.get('error_message'))}")

    # Build DOCX Laporan lokal
    run_dir = repo_root / "artifacts" / run_id
    meta_path = run_dir / "metadata.json"
    docx_path = build_docx_report(meta_path)
    print(f"📄 Laporan DOCX berhasil dikompilasi: {docx_path.relative_to(repo_root)}")

    if no_publish:
        print(f"ℹ️  Publikasi otomatis dilewati (--no-publish). Jalankan 'python3 cli.py publish {run_id}' untuk publikasi.")
        return 0 if verdict == "PASSED" else 1

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
    force = getattr(args, "force", False)
    print(f"📤 Mencoba publikasi ulang artefak untuk Run ID: {run_id} (force={force})")
    pub_result = publish_artifacts(run_id, force=force)
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
    parser_run.add_argument("--no-publish", action="store_true", help="Jangan otomatis unggah ke Google Drive/Docs")
    parser_run.set_defaults(func=cmd_run)

    parser_pub = subparsers.add_parser("publish", help="Publikasikan artefak ke Google Drive")
    parser_pub.add_argument("run_id", help="ID Run yang akan dipublikasikan")
    parser_pub.add_argument("--force", action="store_true", help="Paksa pembaruan dokumen dan pemindahan folder")
    parser_pub.set_defaults(func=cmd_publish)

    parser_list = subparsers.add_parser("list", help="Daftar riwayat eksekusi pengujian")
    parser_list.set_defaults(func=cmd_list)

    parser_approve = subparsers.add_parser("approve", help="Verifikasi dan setujui kasus uji dengan kalkulasi hash kanonikal")
    parser_approve.add_argument("test_case", help="Path file kasus uji markdown yang akan di-approve")
    parser_approve.set_defaults(func=cmd_approve)

    args = parser.parse_args()
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
