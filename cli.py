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
from runner.config import create_project_config, load_project_config, load_project_env
from runner.adapters.jira import (
    JiraClient,
    extract_text_from_description,
    extract_test_case_references,
    extract_qa_scenario_block,
    format_jira_verdict_comment
)
from reporter.docx_builder import build_docx_report
from reporter.publisher import publish_artifacts

def cmd_config(args):
    project_root = Path(args.project_root).resolve()
    project_id = args.project_id or project_root.name
    base_url = args.base_url
    enable_gdrive = args.gdrive
    overwrite = args.overwrite

    if not base_url:
        print("\n🔧 [SAQA Config] Onboarding Konfigurasi Proyek")
        print(f"📁 Target Project Root: {project_root}")
        if not args.project_id:
            try:
                p_in = input(f"Masukkan Project ID/slug [{project_id}]: ").strip()
                if p_in:
                    project_id = p_in
                b_in = input("Masukkan Target Dev Base URL (misal: https://dev.example.com): ").strip()
                while not b_in:
                    b_in = input("Base URL wajib diisi: ").strip()
                base_url = b_in
                g_in = input("Aktifkan ekspor laporan ke Google Drive/Docs? (y/N): ").strip().lower()
                enable_gdrive = g_in.startswith("y")
            except (EOFError, KeyboardInterrupt):
                print("\nKonfigurasi dibatalkan.")
                return 1
        else:
            print("❌ Parameter --base-url wajib diisi saat mode non-interaktif.")
            return 1

    try:
        cfg_file = create_project_config(
            project_root=project_root,
            project_id=project_id,
            base_url=base_url,
            enable_google_drive=enable_gdrive,
            overwrite=overwrite
        )
        print(f"✅ Konfigurasi proyek berhasil disimpan: {cfg_file}")
        print(f"📄 Template environment dibuat di: {project_root / '.env.example'}")
        print("\nLangkah selanjutnya:")
        print("1. Salin .env.example menjadi .env lalu isi kredensial akun uji.")
        print("2. Jalankan pengujian kasus uji Anda:")
        print(f"   python3 cli.py run <test_case.md> --project-root {project_root}")
        return 0
    except Exception as e:
        print(f"❌ Gagal membuat konfigurasi: {str(e)}")
        return 1

def cmd_approve(args):
    project_root = Path(args.project_root).resolve()
    tc_path = project_root / args.test_case if not os.path.isabs(args.test_case) else Path(args.test_case)
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
    print(f"   • File: {tc_path.relative_to(project_root) if tc_path.is_relative_to(project_root) else tc_path}")
    print(f"   • ID: {parsed.get('id')}")
    print(f"   • Approval Hash: {canonical_hash}")
    return 0

def cmd_run(args):
    project_root = Path(args.project_root).resolve()
    test_case_file = args.test_case or "test-cases/TC-001-login-valid.md"
    no_publish = getattr(args, "no_publish", False)
    print(f"\n🚀 [SAQA Runner] Memulai eksekusi Kasus Uji: {test_case_file}")
    print(f"📁 Project Root: {project_root}")
    
    meta = run_test_case(test_case_file, project_root=project_root)
    run_id = meta["run_id"]
    verdict = meta["verdict"]

    print(f"📊 Evaluasi Peramban Selesai:")
    print(f"   • Run ID: {run_id}")
    print(f"   • Project ID: {meta.get('project_id')}")
    print(f"   • Verdict: {verdict}")
    print(f"   • Durasi: {meta.get('execution_duration_seconds')} detik")
    print(f"   • Keterangan: {meta.get('actual_result', meta.get('error_message'))}")

    # Build DOCX Laporan lokal
    run_dir = project_root / "artifacts" / run_id
    meta_path = run_dir / "metadata.json"
    if meta_path.exists():
        docx_path = build_docx_report(meta_path, project_root=project_root)
        print(f"📄 Laporan DOCX berhasil dikompilasi: {docx_path.relative_to(project_root)}")

    if no_publish:
        print(f"ℹ️  Publikasi otomatis dilewati (--no-publish). Jalankan 'python3 cli.py publish {run_id} --project-root {project_root}' untuk publikasi.")
        return 0 if verdict == "PASSED" else 1

    # Attempt Google Drive / Docs Publish jika dikonfigurasi
    pub_result = publish_artifacts(run_id, project_root=project_root)
    if pub_result.get("published"):
        if pub_result.get("status") == "LOCAL_ONLY":
            print(f"ℹ️  {pub_result.get('message')}")
        else:
            print(f"✅ Publikasi Google Drive Sukses:")
            print(f"   • Google Docs: {pub_result.get('google_doc_url')}")
            print(f"   • Bukti Video: {pub_result.get('google_video_url')}")
    else:
        print(f"⚠️  Status Publikasi: {pub_result.get('status', 'UNPUBLISHED')}")
        print(f"   • {pub_result.get('message')}")
        print(f"   • Untuk mencoba publikasi ulang: python3 cli.py publish {run_id} --project-root {project_root}")

    return 0 if verdict == "PASSED" else 1

def cmd_publish(args):
    project_root = Path(args.project_root).resolve()
    run_id = args.run_id
    force = getattr(args, "force", False)
    print(f"📤 Mencoba publikasi ulang artefak untuk Run ID: {run_id} (force={force})")
    pub_result = publish_artifacts(run_id, force=force, project_root=project_root)
    print(json.dumps(pub_result, indent=2))
    return 0 if pub_result.get("published") else 1

def get_jira_client(project_root: Path) -> JiraClient:
    proj_cfg = load_project_config(project_root)
    env_vars = load_project_env(project_root)

    base_url = env_vars.get("JIRA_BASE_URL", "").strip() or proj_cfg.get("environment", {}).get("jira_base_url", "").strip()
    email = env_vars.get("JIRA_EMAIL", "").strip()
    token = env_vars.get("JIRA_API_TOKEN", "").strip()

    if not base_url:
        raise ValueError(
            "JIRA_BASE_URL belum disetel di .env proyek atau saqa.json.\n"
            "Silakan tambahkan JIRA_BASE_URL=https://your-domain.atlassian.net ke file .env proyek."
        )
    if not email or not token:
        raise ValueError(
            "Kredensial Jira (JIRA_EMAIL dan JIRA_API_TOKEN) belum disetel di .env proyek.\n"
            "Silakan tambahkan JIRA_EMAIL=... dan JIRA_API_TOKEN=... ke dalam file .env Anda."
        )
    return JiraClient(base_url, email, token)

def cmd_jira_inspect(args):
    project_root = Path(args.project_root).resolve()
    issue_key = args.issue_key.strip().upper()
    try:
        client = get_jira_client(project_root)
        issue = client.get_issue(issue_key)
        fields = issue.get("fields", {})
        summary = fields.get("summary", "-")
        status = fields.get("status", {}).get("name", "-")
        desc_raw = fields.get("description", "")
        desc_text = extract_text_from_description(desc_raw)

        print(f"\n📋 [Jira Inspect] Tiket: {issue_key}")
        print(f"   • Summary: {summary}")
        print(f"   • Status: {status}")

        test_cases_dir = project_root / "test-cases"
        try:
            refs = extract_test_case_references(desc_text, test_cases_dir)
            print(f"   • Referensi Kasus Uji Ditemukan ({len(refs)}): {[r.name for r in refs]}")
        except Exception as e:
            print(f"   • Referensi Kasus Uji: {str(e)}")

        scenario = extract_qa_scenario_block(desc_text)
        if scenario:
            print(f"   • QA Scenario Block Terdeteksi ({len(scenario.splitlines())} baris)")
        return 0
    except Exception as e:
        print(f"❌ Gagal memeriksa tiket {issue_key}: {str(e)}")
        return 1

def cmd_jira_process(args):
    project_root = Path(args.project_root).resolve()
    issue_key = args.issue_key.strip().upper()
    no_publish = getattr(args, "no_publish", False)

    try:
        client = get_jira_client(project_root)
        proj_cfg = load_project_config(project_root)
        issue = client.get_issue(issue_key)
        fields = issue.get("fields", {})
        summary = fields.get("summary", "-")
        current_status = fields.get("status", {}).get("name", "-")
        desc_raw = fields.get("description", "")
        desc_text = extract_text_from_description(desc_raw)

        print(f"\n🚀 [Jira Process] Memproses Tiket: {issue_key}")
        print(f"   • Summary: {summary}")
        print(f"   • Status Saat Ini: {current_status}")

        # Cek filter status pemicu jika dikonfigurasi
        trigger_statuses = proj_cfg.get("input", {}).get("trigger_statuses", [])
        if trigger_statuses:
            matched_status = any(current_status.strip().lower() == s.strip().lower() for s in trigger_statuses)
            if not matched_status:
                print(f"ℹ️  Tiket berstatus '{current_status}'. Status pemicu yang dikonfigurasi: {trigger_statuses}. Eksekusi dilewati.")
                return 0

        test_cases_dir = project_root / "test-cases"
        refs = []
        try:
            refs = extract_test_case_references(desc_text, test_cases_dir)
        except Exception as ref_err:
            print(f"❌ Kesalahan referensi kasus uji pada tiket: {str(ref_err)}")
            return 1

        if not refs:
            scenario = extract_qa_scenario_block(desc_text)
            if scenario:
                draft_dir = test_cases_dir / "drafts"
                draft_dir.mkdir(parents=True, exist_ok=True)
                draft_file = draft_dir / f"{issue_key}-scenario.md"
                if not draft_file.exists():
                    draft_file.write_text(
                        f"# {issue_key}: Scenario from Jira\n\n"
                        f"- **ID**: {issue_key}\n"
                        f"- **Title**: {summary}\n"
                        f"- **Type**: Positive\n"
                        f"- **Execution Mode**: deterministic\n"
                        f"- **Approval Status**: pending\n\n"
                        f"## Raw QA Scenario\n{scenario}\n",
                        encoding="utf-8"
                    )
                msg = (
                    f"(-) *[SAQA Notice]* Skenario pengujian terdeteksi pada tiket {issue_key}. "
                    f"Draf kasus uji dibuat di `{draft_file.relative_to(project_root)}` dengan status *pending*. "
                    f"Mohon review dan jalankan approve sebelum pengujian dapat dieksekusi."
                )
                if not no_publish:
                    client.post_comment(issue_key, msg)
                print(f"ℹ️  Draf kasus uji dibuat di {draft_file}. Menunggu review & approval manusia.")
                return 0
            else:
                print("❌ Tidak ada referensi kasus uji (TC-xxx) maupun blok QA Scenario pada deskripsi tiket.")
                return 1

        for tc_file in refs:
            print(f"\n▶ Menjalankan Kasus Uji: {tc_file.name}")
            meta = run_test_case(str(tc_file), project_root=project_root)
            run_id = meta["run_id"]
            verdict = meta["verdict"]
            print(f"   • Verdict: {verdict}")

            # Build DOCX report
            run_dir = project_root / "artifacts" / run_id
            meta_path = run_dir / "metadata.json"
            docx_path = build_docx_report(meta_path, project_root=project_root)

            if no_publish:
                print("ℹ️  Publikasi Jira dilewati (--no-publish).")
                continue

            drive_info = None
            # Publikasikan ke Drive jika dikonfigurasi
            drive_outputs = [o for o in proj_cfg.get("outputs", []) if o.get("type") == "google_drive"]
            if drive_outputs:
                drive_info = publish_artifacts(run_id, project_root=project_root)

            # Upload attachments to Jira issue jika jira_comment dikonfigurasi
            jira_outputs = [o for o in proj_cfg.get("outputs", []) if o.get("type") == "jira_comment"]
            if jira_outputs or not proj_cfg.get("outputs"): # Default aktif jika memanggil subperintah jira
                uploaded_attachments = []
                if docx_path.exists():
                    try:
                        att_docx = client.attach_file(issue_key, docx_path)
                        uploaded_attachments.extend(att_docx)
                    except Exception as e_docx:
                        print(f"⚠️  Gagal melampirkan DOCX ke Jira: {str(e_docx)}")

                video_path = run_dir / "evidence.webm"
                if video_path.exists():
                    try:
                        att_vid = client.attach_file(issue_key, video_path)
                        uploaded_attachments.extend(att_vid)
                    except Exception as e_vid:
                        print(f"⚠️  Gagal melampirkan video ke Jira: {str(e_vid)}")

                # Post comment to Jira
                comment_body = format_jira_verdict_comment(meta, uploaded_attachments, drive_info)
                client.post_comment(issue_key, comment_body)
                print(f"✅ Laporan dan bukti attachment berhasil dikirim ke tiket Jira {issue_key}")

        return 0
    except Exception as e:
        print(f"❌ Gagal memproses tiket {issue_key}: {str(e)}")
        return 1

def cmd_jira(args):
    action = args.jira_action
    if action == "inspect":
        return cmd_jira_inspect(args)
    elif action == "process":
        return cmd_jira_process(args)
    else:
        print(f"Aksi jira '{action}' tidak dikenal.")
        return 1

def cmd_list(args):
    project_root = Path(args.project_root).resolve()
    artifacts_dir = project_root / "artifacts"
    if not artifacts_dir.exists():
        print(f"Belum ada riwayat pengujian pada {project_root}.")
        return 0

    runs = sorted([d for d in artifacts_dir.iterdir() if d.is_dir()], reverse=True)
    print(f"\n📋 Daftar Riwayat Eksekusi ({len(runs)} run) di {project_root.name}:")
    print(f"{'Run ID':<32} | {'Test Case':<10} | {'Verdict':<8} | {'Publish Status':<12}")
    print("-" * 75)

    for r in runs:
        meta_file = r / "metadata.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r") as f:
                    m = json.load(f)
                tc_id = m.get("test_case_id", "-")
                v = m.get("verdict", "-")
                pub = "PUBLISHED" if m.get("publish_status", {}).get("published") else "UNPUBLISHED"
                print(f"{r.name:<32} | {tc_id:<10} | {v:<8} | {pub:<12}")
            except Exception:
                print(f"{r.name:<32} | {'(corrupt)':<10} | {'-':<8} | {'-':<12}")
    return 0

def main():
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--project-root", default=argparse.SUPPRESS, help="Root direktori proyek aktif")

    parser = argparse.ArgumentParser(description="SAQA: AI QA Automation CLI", parents=[common_parser])
    parser.set_defaults(project_root=".")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: config / init
    parser_cfg = subparsers.add_parser("config", aliases=["init"], parents=[common_parser], help="Konfigurasi proyek saqa.json dan .env.example")
    parser_cfg.add_argument("--project-id", help="Nama ID/slug proyek")
    parser_cfg.add_argument("--base-url", help="Target Dev Base URL")
    parser_cfg.add_argument("--gdrive", action="store_true", help="Aktifkan output Google Drive/Docs")
    parser_cfg.add_argument("--overwrite", action="store_true", help="Timpa file konfigurasi yang sudah ada")
    parser_cfg.set_defaults(func=cmd_config)

    # Subcommand: run
    parser_run = subparsers.add_parser("run", parents=[common_parser], help="Jalankan Kasus Uji")
    parser_run.add_argument("test_case", nargs="?", default="test-cases/TC-001-login-valid.md", help="Path file kasus uji markdown")
    parser_run.add_argument("--no-publish", action="store_true", help="Jangan otomatis unggah ke Google Drive/Docs")
    parser_run.set_defaults(func=cmd_run)

    # Subcommand: publish
    parser_pub = subparsers.add_parser("publish", parents=[common_parser], help="Publikasikan artefak ke Google Drive")
    parser_pub.add_argument("run_id", help="ID Run yang akan dipublikasikan")
    parser_pub.add_argument("--force", action="store_true", help="Paksa pembaruan dokumen dan pemindahan folder")
    parser_pub.set_defaults(func=cmd_publish)

    # Subcommand: list
    parser_list = subparsers.add_parser("list", parents=[common_parser], help="Daftar riwayat eksekusi pengujian")
    parser_list.set_defaults(func=cmd_list)

    # Subcommand: approve
    parser_approve = subparsers.add_parser("approve", parents=[common_parser], help="Verifikasi dan setujui kasus uji dengan kalkulasi hash kanonikal")
    parser_approve.add_argument("test_case", help="Path file kasus uji markdown yang akan di-approve")
    parser_approve.set_defaults(func=cmd_approve)

    # Subcommand: jira
    parser_jira = subparsers.add_parser("jira", parents=[common_parser], help="Operasi integrasi Jira Cloud")
    jira_subparsers = parser_jira.add_subparsers(dest="jira_action", required=True)

    parser_j_inspect = jira_subparsers.add_parser("inspect", parents=[common_parser], help="Periksa status dan deskripsi tiket Jira")
    parser_j_inspect.add_argument("issue_key", help="Key tiket Jira (misal: MED-101)")

    parser_j_process = jira_subparsers.add_parser("process", parents=[common_parser], help="Proses dan jalankan kasus uji dari tiket Jira")
    parser_j_process.add_argument("issue_key", help="Key tiket Jira (misal: MED-101)")
    parser_j_process.add_argument("--no-publish", action="store_true", help="Jangan otomatis upload ke Google Drive")
    parser_jira.set_defaults(func=cmd_jira)

    args = parser.parse_args()
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
