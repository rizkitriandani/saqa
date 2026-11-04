import os
import json
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional

from runner.config import load_project_config, load_project_env

logger = logging.getLogger("saqa.notifier")

def _send_http_json(url: str, payload: dict, headers: Optional[dict] = None, timeout: int = 10) -> bool:
    """Helper untuk mengirim payload JSON via POST request."""
    req_headers = {"Content-Type": "application/json", "User-Agent": "SAQA-Notifier"}
    if headers:
        req_headers.update(headers)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 201, 202, 204)
    except Exception as e:
        logger.error(f"Gagal mengirim notifikasi HTTP ke {url}: {str(e)}")
        return False

def send_telegram_message(bot_token: str, chat_id: str, text: str, thread_id: Optional[str] = None) -> bool:
    """Mengirim pesan notifikasi ke Telegram Bot API."""
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if thread_id:
        try:
            payload["message_thread_id"] = int(thread_id)
        except ValueError:
            pass
    return _send_http_json(url, payload)

def send_slack_webhook(webhook_url: str, text: str, thread_ts: Optional[str] = None) -> bool:
    """Mengirim pesan notifikasi ke Slack Incoming Webhook."""
    if not webhook_url:
        return False
    payload: Dict[str, Any] = {"text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    return _send_http_json(webhook_url, payload)

def send_discord_webhook(webhook_url: str, text: str) -> bool:
    """Mengirim pesan notifikasi ke Discord Webhook."""
    if not webhook_url:
        return False
    payload: Dict[str, Any] = {"content": text}
    return _send_http_json(webhook_url, payload)

def format_clarification_message(issue_key: str, readiness: dict, session: dict) -> str:
    """
    Menyusun pesan klarifikasi/grilling yang ramah untuk dikirim ke chat tim QA.
    Merangkum isi tiket yang dibaca dan memberikan 3 pilihan sumber yang fleksibel:
    1. Pakai deskripsi tiket langsung
    2. Copas skenario baru di chat
    3. Lampirkan berkas .txt / .md
    """
    reason = readiness.get("reason_code", "UNKNOWN")
    candidate_summary = readiness.get("candidate_summary")
    raw_scenario = readiness.get("raw_scenario")
    unapproved = readiness.get("unapproved_files", [])
    session_id = session.get("session_id", "-")

    lines = [
        f"🔔 *[SAQA Clarification Needed]* Tiket `{issue_key}`",
        f"Tiket baru saja masuk ke antrean pengujian, dan SAQA membaca deskripsi tiket untuk menentukan kasus uji."
    ]

    # Kasus A: Terdeteksi draf / skenario lengkap pada deskripsi tiket
    if candidate_summary and isinstance(candidate_summary, dict):
        lines.extend([
            "",
            "📋 *Kandidat Kasus Uji Terdeteksi pada Deskripsi Tiket:*",
            f"• *ID*: `{candidate_summary.get('id', '-')}`",
            f"• *Judul*: {candidate_summary.get('title', '-')}",
            f"• *Target URL*: `{candidate_summary.get('target_url', '-')}`",
            f"• *Jumlah Langkah*: {candidate_summary.get('steps_count', 0)} langkah",
        ])
        if candidate_summary.get("expected_results"):
            lines.append("• *Ekspektasi Kelulusan*:")
            for exp in candidate_summary["expected_results"][:3]:
                lines.append(f"  - `{exp}`")

        lines.extend([
            "",
            "❓ *Apakah ini test case yang ingin dijalankan?*",
            "Pilih opsi Anda:",
            "1️⃣ Ketik *'Approve & Run'* (atau *'Ya'*) untuk mengesahkan dan menjalankan deskripsi ini langsung.",
            "2️⃣ Salin / tempel teks skenario baru langsung di chat ini.",
            "3️⃣ Lampirkan berkas `.txt` atau `.md` kasus uji pada chat ini."
        ])

    # Kasus B: Terdeteksi teks narasi skenario bahasa alami
    elif raw_scenario:
        lines.extend([
            "",
            "📝 *Skenario Teks Terdeteksi pada Tiket:*",
            "```text",
            raw_scenario[:350] + ("..." if len(raw_scenario) > 350 else ""),
            "```",
            "",
            "❓ *Bagaimana Anda ingin melanjutkan?*",
            "1️⃣ Balas *'Gunakan skenario ini'* untuk meminta AI menyusun draf langkah bakunya.",
            "2️⃣ Salin / tempel teks skenario yang lebih lengkap di chat ini.",
            "3️⃣ Lampirkan berkas `.txt` atau `.md` kasus uji siap pakai."
        ])

    # Kasus C: File referensi ada di repo tapi belum di-approve
    elif unapproved:
        lines.extend([
            "",
            f"⚠️ *Kasus uji ditemukan di repositori namun berstatus 'pending':*",
            f"• Berkas: `{', '.join([u['file'] for u in unapproved])}`",
            "",
            "Ketik *'Approve & Run'* untuk mengesahkan dan langsung mengeksekusi berkas tersebut."
        ])

    # Kasus D: Tiket kosong / tanpa referensi
    else:
        lines.extend([
            "",
            "⚠️ *Deskripsi tiket belum memuat skenario pengujian yang dapat dikenali.*",
            "",
            "Silakan pilih cara untuk memberikan test case:",
            "1️⃣ Salin / tempel langkah pengujian langsung di chat ini.",
            "2️⃣ Lampirkan berkas `.txt` atau `.md` kasus uji.",
            "3️⃣ Balas chat ini untuk mulai sesi tanya-jawab (grilling) bersama AI."
        ])

    lines.extend([
        "",
        f"_Sesi Klarifikasi ID: `{session_id}`_"
    ])
    return "\n".join(lines)

def dispatch_clarification_prompt(
    project_root: Path,
    issue_key: str,
    readiness: dict,
    session: dict
) -> bool:
    """
    Dispatcher netral kanal untuk mengirimkan notifikasi kebutuhan klarifikasi
    ke channel yang dikonfigurasi pada saqa.json atau .env.
    """
    cfg = load_project_config(project_root)
    env_vars = load_project_env(project_root)

    notif_cfg = cfg.get("notifications", {})
    channel = notif_cfg.get("channel", "telegram").lower()
    thread_id = notif_cfg.get("thread_id") or session.get("thread_id")
    msg_text = format_clarification_message(issue_key, readiness, session)

    if channel == "telegram":
        token = env_vars.get("SAQA_TELEGRAM_BOT_TOKEN") or env_vars.get("TELEGRAM_BOT_TOKEN")
        chat_id = env_vars.get("SAQA_TELEGRAM_CHAT_ID") or env_vars.get("TELEGRAM_CHAT_ID")
        if token and chat_id:
            return send_telegram_message(token, chat_id, msg_text, thread_id=thread_id)
        else:
            logger.warning("Telegram channel dipilih namun token/chat_id belum disetel di .env.")
            return False

    elif channel == "slack":
        env_key = notif_cfg.get("target_env", "SLACK_WEBHOOK_URL")
        url = env_vars.get(env_key)
        if url:
            return send_slack_webhook(url, msg_text, thread_ts=thread_id)
        else:
            logger.warning(f"Slack webhook URL ({env_key}) belum disetel di .env.")
            return False

    elif channel == "discord":
        env_key = notif_cfg.get("target_env", "DISCORD_WEBHOOK_URL")
        url = env_vars.get(env_key)
        if url:
            return send_discord_webhook(url, msg_text)
        else:
            logger.warning(f"Discord webhook URL ({env_key}) belum disetel di .env.")
            return False

    elif channel in ("webhook", "generic"):
        env_key = notif_cfg.get("target_env", "GENERIC_NOTIFY_WEBHOOK_URL")
        url = env_vars.get(env_key)
        if url:
            payload = {
                "event": "NEEDS_CLARIFICATION",
                "issue_key": issue_key,
                "readiness": readiness,
                "session": session,
                "text": msg_text
            }
            return _send_http_json(url, payload)
        return False

    logger.info(f"Tidak ada kanal notifikasi yang aktif untuk proyek {project_root.name}.")
    return False

def dispatch_execution_result(
    project_root: Path,
    issue_key: str,
    meta: dict,
    drive_info: Optional[dict] = None
) -> bool:
    """
    Dispatcher netral kanal untuk mengirim ringkasan hasil eksekusi pengujian
    ke channel notifikasi yang dikonfigurasi.
    """
    cfg = load_project_config(project_root)
    env_vars = load_project_env(project_root)

    notif_cfg = cfg.get("notifications", {})
    channel = notif_cfg.get("channel", "telegram").lower()
    thread_id = notif_cfg.get("thread_id")

    verdict = meta.get("verdict", "UNKNOWN")
    tc_id = meta.get("test_case_id", "-")
    title = meta.get("title", "-")
    dur = meta.get("execution_duration_seconds", "-")
    actual = meta.get("actual_result", meta.get("error_message", "-"))

    badge = "✅ PASSED" if verdict == "PASSED" else "⛔ BLOCKED" if verdict == "BLOCKED" else "❌ FAILED"
    lines = [
        f"📊 *[SAQA Execution]* {badge} untuk `{issue_key}`",
        f"• *Test Case*: {tc_id} - {title}",
        f"• *Durasi*: {dur} detik",
        f"• *Keterangan*: {actual}",
    ]

    ai_diag = meta.get("ai_diagnosis")
    if ai_diag:
        lines.append(f"• *Analisis AI*: _{ai_diag}_")

    if drive_info and drive_info.get("published"):
        if drive_info.get("google_doc_url"):
            lines.append(f"• [Google Docs Laporan]({drive_info['google_doc_url']})")
        if drive_info.get("google_video_url"):
            lines.append(f"• [Bukti Video Drive]({drive_info['google_video_url']})")

    msg_text = "\n".join(lines)

    if channel == "telegram":
        token = env_vars.get("SAQA_TELEGRAM_BOT_TOKEN") or env_vars.get("TELEGRAM_BOT_TOKEN")
        chat_id = env_vars.get("SAQA_TELEGRAM_CHAT_ID") or env_vars.get("TELEGRAM_CHAT_ID")
        if token and chat_id:
            return send_telegram_message(token, chat_id, msg_text, thread_id=thread_id)
    elif channel == "slack":
        env_key = notif_cfg.get("target_env", "SLACK_WEBHOOK_URL")
        url = env_vars.get(env_key)
        if url:
            return send_slack_webhook(url, msg_text, thread_ts=thread_id)
    elif channel == "discord":
        env_key = notif_cfg.get("target_env", "DISCORD_WEBHOOK_URL")
        url = env_vars.get(env_key)
        if url:
            return send_discord_webhook(url, msg_text)

    return False
