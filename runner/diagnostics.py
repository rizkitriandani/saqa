import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

def get_failure_context(run_id: str, project_root: Path = None) -> Dict[str, Any]:
    """
    Mengumpulkan konteks kegagalan eksekusi pengujian untuk dianalisis oleh AI Agent:
    - Menemukan screenshot titik kegagalan terakhir (error_state, assertion_failure, final_state).
    - Membaca metadata eksekusi, pesan error, dan asersi yang gagal.
    - Menyiapkan snapshot kasus uji yang dijalankan.
    """
    if project_root is None:
        project_root = Path.cwd()
    project_root = Path(project_root).resolve()

    safe_run_id = Path(run_id).name
    run_dir = project_root / "artifacts" / safe_run_id
    meta_path = run_dir / "metadata.json"

    if not meta_path.exists():
        raise FileNotFoundError(f"metadata.json untuk {safe_run_id} tidak ditemukan di {project_root}.")

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # Identifikasi tangkapan layar kegagalan
    screenshots = meta.get("artifacts", {}).get("screenshots", [])
    failure_screenshot = None
    if screenshots:
        # Prioritaskan error_state atau assertion_failure jika ada
        for sc in reversed(screenshots):
            sc_name = Path(sc).name.lower()
            if "error" in sc_name or "assertion" in sc_name or "final" in sc_name:
                failure_screenshot = sc
                break
        if not failure_screenshot:
            failure_screenshot = screenshots[-1]

    snapshot_path = run_dir / "test-case-snapshot.md"
    snapshot_content = snapshot_path.read_text(encoding="utf-8") if snapshot_path.exists() else None

    return {
        "run_id": safe_run_id,
        "test_case_id": meta.get("test_case_id", "-"),
        "title": meta.get("title", "-"),
        "verdict": meta.get("verdict", "UNKNOWN"),
        "target_url": meta.get("target_url", ""),
        "actual_result": meta.get("actual_result", ""),
        "error_message": meta.get("error_message"),
        "total_steps": len(meta.get("steps", [])),
        "steps_summary": [
            {
                "step_number": s.get("step_number"),
                "action": s.get("action"),
                "status": s.get("status"),
                "notes": s.get("notes")
            }
            for s in meta.get("steps", [])
        ],
        "failure_screenshot_path": failure_screenshot,
        "test_case_snapshot": snapshot_content,
        "existing_diagnosis": meta.get("ai_diagnosis")
    }

def attach_ai_diagnosis(run_id: str, diagnosis_text: str, project_root: Path = None) -> Dict[str, Any]:
    """
    Menyematkan hasil analisis diagnosis AI ke dalam metadata run dan mengompilasi ulang report.docx.
    """
    if project_root is None:
        project_root = Path.cwd()
    project_root = Path(project_root).resolve()

    safe_run_id = Path(run_id).name
    run_dir = project_root / "artifacts" / safe_run_id
    meta_path = run_dir / "metadata.json"

    if not meta_path.exists():
        raise FileNotFoundError(f"metadata.json untuk {safe_run_id} tidak ditemukan di {project_root}.")

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    meta["ai_diagnosis"] = diagnosis_text.strip()

    # Tulis atomik
    tmp_path = meta_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    tmp_path.replace(meta_path)

    # Re-build docx report agar analisis AI masuk ke dokumen laporan
    from reporter.docx_builder import build_docx_report
    drive_video_url = meta.get("publish_status", {}).get("google_video_url")
    docx_path = build_docx_report(meta_path, drive_video_url=drive_video_url, project_root=project_root)

    return {
        "run_id": safe_run_id,
        "ai_diagnosis": meta["ai_diagnosis"],
        "report_docx": str(docx_path.relative_to(project_root))
    }
