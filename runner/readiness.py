import os
import re
import json
import sqlite3
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from runner.parser import (
    parse_markdown_test_case,
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
    MISSING_TEST_CASE_REFERENCE = "MISSING_TEST_CASE_REFERENCE"
    TEST_CASE_NOT_FOUND = "TEST_CASE_NOT_FOUND"
    TEST_CASE_NOT_APPROVED = "TEST_CASE_NOT_APPROVED"
    AMBIGUOUS_TEST_CASE_REFERENCE = "AMBIGUOUS_TEST_CASE_REFERENCE"
    CONTRACT_VALIDATION_FAILED = "CONTRACT_VALIDATION_FAILED"
    RAW_SCENARIO_DETECTED = "RAW_SCENARIO_DETECTED"
    STATUS_SKIPPED = "STATUS_SKIPPED"

class ActionRequired:
    RUN = "RUN"
    INITIATE_CLARIFICATION = "INITIATE_CLARIFICATION"
    WAIT_APPROVAL = "WAIT_APPROVAL"
    FIX_AMBIGUITY = "FIX_AMBIGUITY"
    FIX_CONTRACT = "FIX_CONTRACT"
    NO_OP = "NO_OP"

def evaluate_ticket_readiness(
    description_raw: Any,
    project_root: Path,
    test_cases_dir_rel: str = "test-cases"
) -> Dict[str, Any]:
    """
    Evaluasi kesiapan tiket secara terstruktur dan fail-closed.
    Mengembalikan payload kesiapan dengan reason_code dan action_required yang jelas.
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
        "referenced_ids": []
    }

    # 1. Cek apakah ada referensi TC-xxx di bawah Test Cases
    try:
        refs = extract_test_case_references(desc_text, test_cases_dir)
    except ValueError as ve:
        result["reason_code"] = ReasonCode.AMBIGUOUS_TEST_CASE_REFERENCE
        result["action_required"] = ActionRequired.FIX_AMBIGUITY
        result["details"] = str(ve)
        return result
    except FileNotFoundError as fe:
        # Salah satu ID tidak ditemukan di folder test-cases
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

    # 2. Jika ada referensi berkas yang valid
    if refs:
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

        # Seluruh berkas terverifikasi siap dieksekusi!
        result["ready"] = True
        result["reason_code"] = ReasonCode.READY
        result["action_required"] = ActionRequired.RUN
        result["test_case_paths"] = [str(r.relative_to(project_root)) for r in refs]
        result["details"] = f"Seluruh {len(refs)} kasus uji terverifikasi valid dan disetujui."
        return result

    # 3. Jika tidak ada referensi TC-xxx, cek apakah ada blok QA Scenario bahasa alami
    scenario = extract_qa_scenario_block(desc_text)
    if scenario:
        result["reason_code"] = ReasonCode.RAW_SCENARIO_DETECTED
        result["action_required"] = ActionRequired.INITIATE_CLARIFICATION
        result["raw_scenario"] = scenario
        result["details"] = (
            "Ditemukan blok 'QA Scenario' bahasa alami. "
            "Sistem perlu memicu sesi klarifikasi AI (grilling) untuk memformulasikan kasus uji terstruktur."
        )
        return result

    # 4. Tiket benar-benar kosong dari skenario pengujian
    result["reason_code"] = ReasonCode.MISSING_TEST_CASE_REFERENCE
    result["action_required"] = ActionRequired.INITIATE_CLARIFICATION
    result["details"] = (
        "Deskripsi tiket tidak memuat bagian 'Test Cases' maupun 'QA Scenario'. "
        "Perlu sesi klarifikasi untuk menggali kebutuhan pengujian dari tim QA."
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
