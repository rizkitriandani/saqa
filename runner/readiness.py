import os
import re
import json
import sqlite3
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from runner.parser import (
    parse_markdown_test_case,
    parse_markdown_test_case_content,
    validate_test_case_contract,
    compute_canonical_content_hash
)
from runner.adapters.jira import (
    extract_text_from_description,
    extract_test_case_references,
    extract_qa_scenario_block
)

class ReasonCode:
    READY = "READY"
    INLINE_TEST_CASE_DETECTED = "INLINE_TEST_CASE_DETECTED"
    MISSING_TEST_CASE_REFERENCE = "MISSING_TEST_CASE_REFERENCE"
    TEST_CASE_NOT_FOUND = "TEST_CASE_NOT_FOUND"
    TEST_CASE_NOT_APPROVED = "TEST_CASE_NOT_APPROVED"
    AMBIGUOUS_TEST_CASE_REFERENCE = "AMBIGUOUS_TEST_CASE_REFERENCE"
    CONTRACT_VALIDATION_FAILED = "CONTRACT_VALIDATION_FAILED"
    RAW_SCENARIO_DETECTED = "RAW_SCENARIO_DETECTED"
    EMPTY_DESCRIPTION = "EMPTY_DESCRIPTION"
    STATUS_SKIPPED = "STATUS_SKIPPED"

class ActionRequired:
    RUN = "RUN"
    INITIATE_CLARIFICATION = "INITIATE_CLARIFICATION"
    WAIT_APPROVAL = "WAIT_APPROVAL"
    FIX_AMBIGUITY = "FIX_AMBIGUITY"
    FIX_CONTRACT = "FIX_CONTRACT"
    NO_OP = "NO_OP"

def is_scenario_like_text(text: str) -> bool:
    """Mengecek apakah teks deskripsi memuat pola instruksi pengujian/skenario bahasa alami."""
    keywords = r'\b(step|langkah|alur|skenario|scenario|klik|click|buka|navigate|fill|isi|expected|hasil|aspek|login)\b'
    matches = re.findall(keywords, text, re.IGNORECASE)
    return len(matches) >= 2

def is_full_inline_test_case(desc_text: str) -> bool:
    """Mengecek apakah teks deskripsi memuat spesifikasi kasus uji Markdown lengkap."""
    has_id = bool(re.search(r'(?:^|\n)\s*(?:#\s*TC-\d+|\*\*\s*ID\s*\*\*\s*:\s*TC-\d+)', desc_text, re.IGNORECASE))
    has_steps = bool(re.search(r'Test\s+Steps|Langkah\s+Pengujian', desc_text, re.IGNORECASE))
    has_expected = bool(re.search(r'Expected\s+Results|Hasil\s+yang\s+Diharapkan', desc_text, re.IGNORECASE))
    return (has_id or has_steps) and has_expected

def evaluate_ticket_readiness(
    description_raw: Any,
    project_root: Path,
    test_cases_dir_rel: str = "test-cases",
    issue_key: Optional[str] = None,
    ticket_summary: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluasi kesiapan tiket secara terstruktur dan fail-closed.
    Mendukung 3 sumber masukan:
    1. Referensi berkas Git repo di bawah 'Test Cases' (misal: - TC-001)
    2. Inline full test case Markdown yang ditempel langsung di deskripsi tiket Jira
    3. Blok 'QA Scenario' bahasa alami atau teks deskripsi bebas untuk klarifikasi
    """
    desc_text = extract_text_from_description(description_raw)
    test_cases_dir = project_root / test_cases_dir_rel

    result: Dict[str, Any] = {
        "ready": False,
        "reason_code": ReasonCode.MISSING_TEST_CASE_REFERENCE,
        "action_required": ActionRequired.INITIATE_CLARIFICATION,
        "details": "",
        "test_case_paths": [],
        "unapproved_files": [],
        "missing_ids": [],
        "raw_scenario": None,
        "referenced_ids": [],
        "candidate_summary": None,
        "candidate_source_type": None # "inline_markdown", "repo_reference", "raw_scenario", "empty"
    }

    if not desc_text.strip():
        result["reason_code"] = ReasonCode.EMPTY_DESCRIPTION
        result["candidate_source_type"] = "empty"
        result["details"] = "Deskripsi tiket kosong. Perlu sesi klarifikasi untuk menyusun skenario pengujian."
        return result

    # 1. Jalur A: Deteksi Kasus Uji Markdown Lengkap (Inline Test Case)
    # Keamanan: Evaluasi murni in-memory (read-only) tanpa menulis berkas ke disk.
    # Seluruh inline test case dari deskripsi tiket diperlakukan sebagai kandidat sumber
    # yang WAJIB diverifikasi manusia (tidak boleh auto-run meskipun teks deskripsi memuat 'approved').
    if is_full_inline_test_case(desc_text):
        result["candidate_source_type"] = "inline_markdown"
        parsed = parse_markdown_test_case_content(desc_text)

        # Fallback ID & Title jika tidak ditulis eksplisit di dalam bodi deskripsi
        if parsed.get("id") == "UNKNOWN":
            m_id = re.search(r'\b(TC-\d+)\b', desc_text, re.IGNORECASE)
            if m_id:
                parsed["id"] = m_id.group(1).upper()
            elif ticket_summary and re.search(r'\b(TC-\d+)\b', ticket_summary, re.IGNORECASE):
                parsed["id"] = re.search(r'\b(TC-\d+)\b', ticket_summary, re.IGNORECASE).group(1).upper()
            elif issue_key:
                parsed["id"] = issue_key

        if parsed.get("title") == "Unknown Test Case":
            if ticket_summary:
                parsed["title"] = ticket_summary
            elif issue_key:
                parsed["title"] = f"Test Scenario for {issue_key}"

        c_errors = validate_test_case_contract(parsed)
        tc_id = parsed.get("id") or (issue_key or "INLINE")

        result["candidate_summary"] = {
            "id": tc_id,
            "title": parsed.get("title"),
            "target_url": parsed.get("target_url"),
            "steps_count": len(parsed.get("steps", [])),
            "expected_results": parsed.get("expected_results", []),
            "approval_status": parsed.get("approval_status", "pending")
        }

        if c_errors:
            result["reason_code"] = ReasonCode.CONTRACT_VALIDATION_FAILED
            result["action_required"] = ActionRequired.FIX_CONTRACT
            result["details"] = f"Validasi kontrak kasus uji inline gagal: {'; '.join(c_errors)}"
            result["candidate_summary"]["contract_errors"] = c_errors
            return result

        result["ready"] = False
        result["reason_code"] = ReasonCode.INLINE_TEST_CASE_DETECTED
        result["action_required"] = ActionRequired.WAIT_APPROVAL
        result["referenced_ids"] = [tc_id]
        result["details"] = (
            f"Spesifikasi kasus uji lengkap '{tc_id}' terdeteksi pada deskripsi tiket. "
            "Perlu konfirmasi/approval manusia sebelum peramban dijalankan."
        )
        return result

    # 2. Jalur B: Cek Referensi TC-xxx di bawah Test Cases
    try:
        refs = extract_test_case_references(desc_text, test_cases_dir)
    except ValueError as ve:
        result["reason_code"] = ReasonCode.AMBIGUOUS_TEST_CASE_REFERENCE
        result["action_required"] = ActionRequired.FIX_AMBIGUITY
        result["details"] = str(ve)
        return result
    except FileNotFoundError as fe:
        missing_id = ""
        m = re.search(r"'(TC-\d+)'", str(fe))
        if m:
            missing_id = m.group(1)
        result["reason_code"] = ReasonCode.TEST_CASE_NOT_FOUND
        result["action_required"] = ActionRequired.INITIATE_CLARIFICATION
        result["missing_ids"] = [missing_id] if missing_id else []
        result["details"] = (
            f"Berkas untuk kasus uji '{missing_id or 'tercantum'}' tidak ditemukan di repositori. "
            "Perlu sesi klarifikasi untuk menyusun skenario kasus uji tersebut."
        )
        return result

    if refs:
        result["candidate_source_type"] = "repo_reference"
        result["referenced_ids"] = [f.stem.split("-")[0] for f in refs]
        unapproved = []
        contract_errors = []

        for tc_file in refs:
            parsed = parse_markdown_test_case(tc_file)
            c_errors = validate_test_case_contract(parsed)
            if c_errors:
                contract_errors.append(f"{tc_file.name}: {'; '.join(c_errors)}")
                continue

            app_status = parsed.get("approval_status", "pending").lower()
            app_hash = parsed.get("approval_hash")
            canon_hash = compute_canonical_content_hash(parsed.get("raw_content", ""))

            if app_status != "approved" or not app_hash or app_hash != canon_hash:
                unapproved.append({
                    "file": str(tc_file.relative_to(project_root)),
                    "id": parsed.get("id"),
                    "status": app_status,
                    "reason": "Hash mismatch atau status pending"
                })

        if contract_errors:
            result["reason_code"] = ReasonCode.CONTRACT_VALIDATION_FAILED
            result["action_required"] = ActionRequired.FIX_CONTRACT
            result["details"] = f"Validasi kontrak kasus uji gagal: {'; '.join(contract_errors)}"
            return result

        if unapproved:
            result["reason_code"] = ReasonCode.TEST_CASE_NOT_APPROVED
            result["action_required"] = ActionRequired.WAIT_APPROVAL
            result["unapproved_files"] = unapproved
            result["details"] = (
                f"Terdapat {len(unapproved)} kasus uji yang belum disetujui (unapproved/pending): "
                f"{[u['file'] for u in unapproved]}. Perlu review manusia sebelum dapat dijalankan."
            )
            return result

        result["ready"] = True
        result["reason_code"] = ReasonCode.READY
        result["action_required"] = ActionRequired.RUN
        result["test_case_paths"] = [str(r.relative_to(project_root)) for r in refs]
        result["details"] = f"Seluruh {len(refs)} kasus uji terverifikasi valid dan disetujui."
        return result

    # 3. Jalur C: Blok QA Scenario bahasa alami atau deskripsi bebas yang menyerupai skenario
    scenario = extract_qa_scenario_block(desc_text)
    if not scenario and is_scenario_like_text(desc_text):
        # Jika tidak ada heading khusus tapi ada teks deskripsi yang memuat alur langkah
        scenario = desc_text.strip()

    if scenario:
        result["candidate_source_type"] = "raw_scenario"
        result["reason_code"] = ReasonCode.RAW_SCENARIO_DETECTED
        result["action_required"] = ActionRequired.INITIATE_CLARIFICATION
        result["raw_scenario"] = scenario
        result["details"] = (
            "Skenario pengujian terdeteksi pada deskripsi tiket. "
            "Sistem perlu mengonfirmasi apakah skenario ini yang ingin dijalankan atau ada bentuk lain."
        )
        return result

    result["reason_code"] = ReasonCode.MISSING_TEST_CASE_REFERENCE
    result["candidate_source_type"] = "empty"
    result["action_required"] = ActionRequired.INITIATE_CLARIFICATION
    result["details"] = (
        "Deskripsi tiket tidak memuat spesifikasi kasus uji yang terstruktur. "
        "Perlu sesi klarifikasi untuk menyusun skenario pengujian."
    )
    return result


def init_clarification_db(db_path: Path):
    """Inisialisasi tabel clarification_sessions untuk tracking percakapan klarifikasi."""
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clarification_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                project_id TEXT NOT NULL,
                issue_key TEXT NOT NULL,
                status TEXT NOT NULL, -- PENDING_CLARIFICATION, DRAFTED, APPROVED, CANCELLED
                channel TEXT,         -- telegram, slack, discord, etc.
                channel_target TEXT,  -- chat_id, channel_name, webhook_url
                thread_id TEXT,       -- thread/topic id for threaded discussions
                raw_scenario TEXT,
                draft_path TEXT,
                draft_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_active_clarifications 
            ON clarification_sessions(project_id, issue_key, status);
        """)
        conn.commit()


def create_or_get_clarification_session(
    db_path: Path,
    project_id: str,
    issue_key: str,
    raw_scenario: Optional[str] = None,
    channel: Optional[str] = None,
    channel_target: Optional[str] = None,
    thread_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Membuat sesi klarifikasi baru atau mengambil sesi yang sedang aktif (PENDING_CLARIFICATION/DRAFTED)
    untuk issue_key yang sama agar percakapan tetap terikat dan tidak membuat sesi duplikat.
    """
    init_clarification_db(db_path)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clean_key = issue_key.strip().upper()

    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Cek apakah sudah ada sesi aktif untuk issue ini
        cur.execute("""
            SELECT * FROM clarification_sessions
            WHERE project_id = ? AND issue_key = ? AND status IN ('PENDING_CLARIFICATION', 'DRAFTED')
            ORDER BY id DESC LIMIT 1;
        """, (project_id, clean_key))
        existing = cur.fetchone()
        if existing:
            return dict(existing)

        session_id = f"clarify_{clean_key}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        cur.execute("""
            INSERT INTO clarification_sessions (
                session_id, project_id, issue_key, status, channel, channel_target, thread_id,
                raw_scenario, created_at, updated_at
            ) VALUES (?, ?, ?, 'PENDING_CLARIFICATION', ?, ?, ?, ?, ?, ?);
        """, (session_id, project_id, clean_key, channel, channel_target, thread_id, raw_scenario, now_iso, now_iso))
        conn.commit()

        cur.execute("SELECT * FROM clarification_sessions WHERE session_id = ?;", (session_id,))
        return dict(cur.fetchone())


def update_clarification_draft(
    db_path: Path,
    session_id: str,
    draft_path: str,
    draft_hash: str
):
    """Memperbarui path draf dan hash kanonikal saat AI telah menyusun skenario."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        conn.execute("""
            UPDATE clarification_sessions
            SET draft_path = ?, draft_hash = ?, status = 'DRAFTED', updated_at = ?
            WHERE session_id = ?;
        """, (draft_path, draft_hash, now_iso, session_id))
        conn.commit()
