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
    format_jira_verdict_comment,
    publish_jira_artifacts
)
from runner.readiness import (
    evaluate_ticket_readiness,
    ReasonCode,
    ActionRequired,
    create_or_get_clarification_session
)
from runner.adapters.job_queue import get_db_path
from runner.adapters.notifier import dispatch_clarification_prompt, dispatch_execution_result
from runner.diagnostics import get_failure_context, attach_ai_diagnosis
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
    jira_issue = getattr(args, "jira_issue", None)
    print(f"📤 Mencoba publikasi ulang artefak untuk Run ID: {run_id} (force={force})")
    pub_result = publish_artifacts(run_id, force=force, project_root=project_root)
    print(json.dumps(pub_result, indent=2))

    if jira_issue:
        try:
            proj_cfg = load_project_config(project_root)
            allowed_keys = proj_cfg.get("environment", {}).get("project_keys", [])
            clean_issue = jira_issue.strip().upper()
            if allowed_keys:
                prefix = clean_issue.split("-")[0]
                if prefix not in allowed_keys:
                    print(f"❌ Project key '{prefix}' tidak ada dalam allowlist proyek: {allowed_keys}")
                    return 1

            client = get_jira_client(project_root)
            res_j = publish_jira_artifacts(run_id, clean_issue, client, project_root, drive_info=pub_result, force=force)
            print(f"✅ Publikasi ke tiket Jira {clean_issue} selesai:")
            print(json.dumps(res_j, indent=2))
        except Exception as e_j:
            print(f"❌ Gagal mempublikasikan ke Jira {jira_issue}: {str(e_j)}")
            return 1

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
        proj_cfg = load_project_config(project_root)
        allowed_keys = proj_cfg.get("environment", {}).get("project_keys", [])
        if allowed_keys:
            proj_prefix = issue_key.split("-")[0]
            if proj_prefix not in allowed_keys:
                print(f"❌ Project key '{proj_prefix}' tidak ada dalam allowlist proyek: {allowed_keys}")
                return 1

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

        tc_dir_rel = proj_cfg.get("input", {}).get("test_cases_dir", "test-cases")
        test_cases_dir = project_root / tc_dir_rel
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

def cmd_jira_validate(args):
    project_root = Path(args.project_root).resolve()
    issue_key = args.issue_key.strip().upper()
    try:
        proj_cfg = load_project_config(project_root)
        allowed_keys = proj_cfg.get("environment", {}).get("project_keys", [])
        if allowed_keys:
            proj_prefix = issue_key.split("-")[0]
            if proj_prefix not in allowed_keys:
                print(f"❌ Project key '{proj_prefix}' tidak ada dalam allowlist proyek: {allowed_keys}")
                return 1

        client = get_jira_client(project_root)
        issue = client.get_issue(issue_key)
        fields = issue.get("fields", {})
        summary = fields.get("summary", "-")
        status = fields.get("status", {}).get("name", "-")
        desc_raw = fields.get("description", "")

        tc_dir_rel = proj_cfg.get("input", {}).get("test_cases_dir", "test-cases")
        readiness = evaluate_ticket_readiness(
            desc_raw, project_root, test_cases_dir_rel=tc_dir_rel, issue_key=issue_key, ticket_summary=summary
        )

        print(f"\n🔍 [Jira Validate] Evaluasi Kesiapan Tiket: {issue_key}")
        print(f"   • Summary: {summary}")
        print(f"   • Status: {status}")
        print(f"   • Status Kesiapan (Ready): {'✅ SIAP DIEKSEKUSI' if readiness['ready'] else '⚠️ BUTUH KLARIFIKASI/APPROVAL'}")
        print(f"   • Reason Code: {readiness['reason_code']}")
        print(f"   • Action Required: {readiness['action_required']}")
        print(f"   • Keterangan: {readiness['details']}")
        if readiness["referenced_ids"]:
            print(f"   • Referensi Terdeteksi: {readiness['referenced_ids']}")
        if readiness["unapproved_files"]:
            print(f"   • Kasus Uji Belum Disetujui: {[u['file'] for u in readiness['unapproved_files']]}")

        return 0 if readiness["ready"] else 1
    except Exception as e:
        print(f"❌ Gagal memvalidasi tiket {issue_key}: {str(e)}")
        return 1

def cmd_jira_process(args):
    project_root = Path(args.project_root).resolve()
    issue_key = args.issue_key.strip().upper()
    no_publish = getattr(args, "no_publish", False)

    try:
        proj_cfg = load_project_config(project_root)
        allowed_keys = proj_cfg.get("environment", {}).get("project_keys", [])
        if allowed_keys:
            proj_prefix = issue_key.split("-")[0]
            if proj_prefix not in allowed_keys:
                print(f"❌ Project key '{proj_prefix}' tidak ada dalam allowlist proyek: {allowed_keys}")
                return 1

        client = get_jira_client(project_root)
        issue = client.get_issue(issue_key)
        fields = issue.get("fields", {})
        summary = fields.get("summary", "-")
        current_status = fields.get("status", {}).get("name", "-")
        desc_raw = fields.get("description", "")

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

        tc_dir_rel = proj_cfg.get("input", {}).get("test_cases_dir", "test-cases")
        readiness = evaluate_ticket_readiness(
            desc_raw, project_root, test_cases_dir_rel=tc_dir_rel, issue_key=issue_key, ticket_summary=summary
        )

        # Jika tiket belum siap dieksekusi (perlu klarifikasi/approval)
        if not readiness["ready"]:
            reason_code = readiness["reason_code"]
            action_req = readiness["action_required"]
            details = readiness["details"]
            print(f"⚠️  Tiket {issue_key} belum siap dieksekusi: [{reason_code}]")
            print(f"   • Details: {details}")
            print(f"   • Action Required: {action_req}")

            # 1. Simpan sesi klarifikasi di SQLite dengan konten skenario yang terdeteksi
            db_path = get_db_path(project_root)
            notif_cfg = proj_cfg.get("notifications", {})
            channel = notif_cfg.get("channel", "telegram")
            scenario_payload = readiness.get("raw_scenario") or (desc_text if readiness.get("candidate_source_type") == "inline_markdown" else None)
            session = create_or_get_clarification_session(
                db_path=db_path,
                project_id=proj_cfg.get("project_id", project_root.name),
                issue_key=issue_key,
                raw_scenario=scenario_payload,
                channel=channel
            )

            # 2. Buat berkas draf di test-cases/drafts/ untuk ditinjau manusia jika belum ada
            draft_dir = project_root / tc_dir_rel / "drafts"
            draft_dir.mkdir(parents=True, exist_ok=True)
            draft_file = draft_dir / f"{issue_key}-scenario.md"

            if readiness.get("candidate_source_type") == "inline_markdown" and not draft_file.exists():
                draft_file.write_text(desc_text, encoding="utf-8")
            elif readiness.get("raw_scenario") and not draft_file.exists():
                draft_file.write_text(
                    f"# {issue_key}: Scenario from Jira\n\n"
                    f"- **ID**: {issue_key}\n"
                    f"- **Title**: {summary}\n"
                    f"- **Type**: Positive\n"
                    f"- **Execution Mode**: deterministic\n"
                    f"- **Approval Status**: pending\n\n"
                    f"## Raw QA Scenario\n{readiness['raw_scenario']}\n",
                    encoding="utf-8"
                )

            # 3. Dispatch notifikasi klarifikasi ke channel yang dikonfigurasi
            if not no_publish:
                dispatch_clarification_prompt(project_root, issue_key, readiness, session)

            # 4. Jika output Jira aktif, beri komentar notifikasi ramah di Jira
            jira_outputs = [o for o in proj_cfg.get("outputs", []) if o.get("type") == "jira_comment"]
            if not no_publish and (jira_outputs or not proj_cfg.get("outputs")):
                msg = (
                    f"(-) *[SAQA Notice]* Tiket {issue_key} masuk status pengujian namun belum siap dieksekusi.\n"
                    f"* *Status Kesiapan*: `{reason_code}`\n"
                    f"* *Catatan*: {details}\n"
                    f"* *Tindakan*: Tim QA dapat membalas chat bot atau menjalankan `/saqa audit` untuk memvalidasi skenario."
                )
                try:
                    client.post_comment(issue_key, msg)
                except Exception as e_cmt:
                    print(f"⚠️ Gagal memposting komentar ke Jira: {e_cmt}")

            # Return 2 to signal NEEDS_CLARIFICATION to caller/worker
            return 2

        # Jika sudah siap, eksekusi setiap test case
        for tc_rel in readiness["test_case_paths"]:
            tc_file = project_root / tc_rel
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
                print("ℹ️  Publikasi dilewati (--no-publish).")
                continue

            drive_info = None
            # Publikasikan ke Drive jika dikonfigurasi
            drive_outputs = [o for o in proj_cfg.get("outputs", []) if o.get("type") == "google_drive"]
            if drive_outputs:
                drive_info = publish_artifacts(run_id, project_root=project_root)

            # Upload attachments dan komentar ke Jira secara idempoten jika dikonfigurasi
            jira_outputs = [o for o in proj_cfg.get("outputs", []) if o.get("type") == "jira_comment"]
            if jira_outputs or not proj_cfg.get("outputs"): # Default aktif saat memanggil subperintah jira
                try:
                    res_jira = publish_jira_artifacts(run_id, issue_key, client, project_root, drive_info=drive_info)
                    print(f"✅ Laporan dan bukti attachment berhasil dikirim ke tiket Jira {issue_key} (Comment ID: {res_jira.get('comment_id')})")
                except Exception as e_jira:
                    print(f"⚠️  Gagal mempublikasikan hasil ke tiket Jira: {str(e_jira)}")
                    return 1

            # Dispatch notifikasi eksekusi ke channel (Telegram/Slack/Discord)
            dispatch_execution_result(project_root, issue_key, meta, drive_info=drive_info)

        return 0
    except Exception as e:
        print(f"❌ Gagal memproses tiket {issue_key}: {str(e)}")
        return 1

def cmd_jira(args):
    action = args.jira_action
    if action == "inspect":
        return cmd_jira_inspect(args)
    elif action == "validate":
        return cmd_jira_validate(args)
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

def cmd_diagnose(args):
    project_root = Path(args.project_root).resolve()
    run_id = args.run_id
    attach_text = getattr(args, "attach", None)
    try:
        if attach_text:
            res = attach_ai_diagnosis(run_id, attach_text, project_root=project_root)
            print(f"✅ Analisis AI berhasil disematkan pada {run_id}:")
            print(f"   • Laporan DOCX diperbarui: {res['report_docx']}")
            return 0
        else:
            ctx = get_failure_context(run_id, project_root=project_root)
            print(f"\n🔍 [SAQA Failure Context] Run ID: {run_id}")
            print(f"   • Kasus Uji: {ctx['test_case_id']} - {ctx['title']}")
            print(f"   • Verdict: {ctx['verdict']}")
            print(f"   • Hasil Aktual: {ctx['actual_result']}")
            if ctx.get("error_message"):
                print(f"   • Pesan Error: {ctx['error_message']}")
            print(f"   • Path Tangkapan Layar: {ctx['failure_screenshot_path']}")
            print("\nKonteks detail (JSON):")
            print(json.dumps(ctx, indent=2))
            return 0
    except Exception as e:
        print(f"❌ Gagal mengambil konteks diagnostik: {str(e)}")
        return 1

def cmd_setup_harness(args):
    target = args.target or "all"
    home = Path.home()
    success = True

    if target in ["all", "pi"]:
        try:
            skills_dir = home / ".agents" / "skills"
            skills_dir.mkdir(parents=True, exist_ok=True)
            skill_link = skills_dir / "saqa"
            skill_src = repo_root / ".agents" / "skills" / "saqa"
            if skill_link.is_symlink() or skill_link.exists():
                skill_link.unlink()
            skill_link.symlink_to(skill_src, target_is_directory=True)

            prompts_dir = home / ".pi" / "agent" / "prompts"
            prompts_dir.mkdir(parents=True, exist_ok=True)
            prompt_link = prompts_dir / "saqa.md"
            prompt_src = repo_root / "prompts" / "saqa.md"
            if prompt_link.is_symlink() or prompt_link.exists():
                prompt_link.unlink()
            prompt_link.symlink_to(prompt_src)

            print("✅ Pi Coding Agent integration registered:")
            print(f"   • Skill: {skill_link} -> {skill_src}")
            print(f"   • Slash Command: {prompt_link} -> {prompt_src}")
        except Exception as e:
            print(f"❌ Failed to register Pi harness: {e}")
            success = False

    if target in ["all", "hermes"]:
        try:
            plugins_dir = home / ".hermes" / "plugins"
            plugins_dir.mkdir(parents=True, exist_ok=True)
            plugin_link = plugins_dir / "saqa"
            plugin_src = repo_root / "plugins" / "hermes"
            if plugin_link.is_symlink() or plugin_link.exists():
                plugin_link.unlink()
            plugin_link.symlink_to(plugin_src, target_is_directory=True)

            h_skills_dir = home / ".hermes" / "skills"
            h_skills_dir.mkdir(parents=True, exist_ok=True)
            h_skill_link = h_skills_dir / "saqa"
            h_skill_src = repo_root / ".agents" / "skills" / "saqa"
            if h_skill_link.is_symlink() or h_skill_link.exists():
                h_skill_link.unlink()
            h_skill_link.symlink_to(h_skill_src, target_is_directory=True)

            print("✅ Hermes Agent integration registered:")
            print(f"   • Plugin: {plugin_link} -> {plugin_src}")
            print(f"   • Skill: {h_skill_link} -> {h_skill_src}")
        except Exception as e:
            print(f"❌ Failed to register Hermes harness: {e}")
            success = False

    if args.playwright:
        import subprocess
        print("\n📥 Installing Playwright Chromium browser binaries...")
        p_res = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
        if p_res.returncode == 0:
            print("✅ Playwright Chromium installed successfully.")
        else:
            print("❌ Failed to install Playwright Chromium.")
            success = False

    return 0 if success else 1

def cmd_webhook(args):
    from runner.adapters.webhook_server import start_webhook_server
    project_root = Path(args.project_root).resolve()
    host = args.host
    port = args.port
    runner = args.runner
    allow_unauth = getattr(args, "allow_unauthenticated", False)
    start_webhook_server(
        host=host,
        port=port,
        project_root=project_root,
        runner_override=runner,
        allow_unauthenticated=allow_unauth
    )
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
    parser_pub = subparsers.add_parser("publish", parents=[common_parser], help="Publikasikan artefak ke Google Drive atau Jira")
    parser_pub.add_argument("run_id", help="ID Run yang akan dipublikasikan")
    parser_pub.add_argument("--jira-issue", help="Key tiket Jira untuk mempublikasikan bukti ke Jira")
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

    parser_j_validate = jira_subparsers.add_parser("validate", parents=[common_parser], help="Evaluasi kesiapan tiket secara terstruktur sebelum pengujian")
    parser_j_validate.add_argument("issue_key", help="Key tiket Jira (misal: MED-101)")

    parser_j_process = jira_subparsers.add_parser("process", parents=[common_parser], help="Proses dan jalankan kasus uji dari tiket Jira")
    parser_j_process.add_argument("issue_key", help="Key tiket Jira (misal: MED-101)")
    parser_j_process.add_argument("--no-publish", action="store_true", help="Jangan otomatis upload ke Google Drive")
    parser_jira.set_defaults(func=cmd_jira)

    # Subcommand: diagnose
    parser_diag = subparsers.add_parser("diagnose", parents=[common_parser], help="Ambil konteks kegagalan eksekusi atau sematkan analisis AI")
    parser_diag.add_argument("run_id", help="ID Run yang gagal (misal: RUN_20261104_xxx)")
    parser_diag.add_argument("--attach", help="Teks analisis akar masalah (root cause) untuk disematkan ke laporan")
    parser_diag.set_defaults(func=cmd_diagnose)

    # Subcommand: setup-harness
    parser_setup = subparsers.add_parser("setup-harness", parents=[common_parser], help="Daftarkan skill & plugin ke Pi Coding Agent dan Hermes secara otomatis")
    parser_setup.add_argument("--target", choices=["all", "pi", "hermes"], default="all", help="Target harness (default: all)")
    parser_setup.add_argument("--playwright", action="store_true", help="Sekaligus install browser Chromium Playwright")
    parser_setup.set_defaults(func=cmd_setup_harness)

    # Subcommand: webhook
    parser_wh = subparsers.add_parser("webhook", parents=[common_parser], help="Jalankan Webhook Receiver Server (VPS listener)")
    parser_wh.add_argument("--host", default="127.0.0.1", help="Host bind address (default: 127.0.0.1; gunakan reverse proxy HTTPS)")
    parser_wh.add_argument("--port", type=int, default=8080, help="Port server (default: 8080)")
    parser_wh.add_argument("--runner", choices=["local", "github", "gitlab"], default=None, help="Pilihan runner: local (default), github, atau gitlab")
    parser_wh.add_argument("--allow-unauthenticated", action="store_true", help="Izinkan menjalankan server tanpa WEBHOOK_SECRET (hanya untuk pengujian lokal)")
    parser_wh.set_defaults(func=cmd_webhook)

    args = parser.parse_args()
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
