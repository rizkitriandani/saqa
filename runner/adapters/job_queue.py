import sqlite3
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

def get_db_path(project_root: Path) -> Path:
    data_dir = project_root / "artifacts"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "saqa_jobs.db"

def init_job_database(db_path: Path):
    """Inisialisasi tabel antrean kerja durable di SQLite dengan mode WAL."""
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS webhook_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                issue_key TEXT NOT NULL,
                runner_target TEXT NOT NULL,
                status TEXT NOT NULL, -- PENDING, RUNNING, COMPLETED, DISPATCHED, FAILED, NEEDS_RECONCILIATION
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, event_id)
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_jobs ON webhook_jobs(status, id);
        """)
        conn.commit()

def reconcile_interrupted_jobs_on_startup(db_path: Path, project_id: str):
    """
    Menandai job yang berstatus 'RUNNING' saat server mati/restart sebagai 'NEEDS_RECONCILIATION'.
    Mencegah pengulangan eksekusi otomatis tanpa pemeriksaan status remote terlebih dahulu.
    """
    if not db_path.exists():
        return
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        conn.execute("""
            UPDATE webhook_jobs
            SET status = 'NEEDS_RECONCILIATION',
                error_message = 'Interrupted: worker terminated while job was RUNNING.',
                updated_at = ?
            WHERE project_id = ? AND status = 'RUNNING';
        """, (now_iso, project_id))
        conn.commit()

def enqueue_job(db_path: Path, project_id: str, event_id: str, issue_key: str, runner_target: str) -> Tuple[Optional[int], bool]:
    """
    Memasukkan job baru ke antrean dengan deduplikasi event_id secara durable di basis data.
    Mengembalikan (job_id, is_duplicate).
    """
    init_job_database(db_path)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with sqlite3.connect(str(db_path), timeout=15.0) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO webhook_jobs (project_id, event_id, issue_key, runner_target, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'PENDING', ?, ?)
            """, (project_id, event_id, issue_key, runner_target, now_iso, now_iso))
            conn.commit()
            return cur.lastrowid, False
    except sqlite3.IntegrityError:
        # Event ID duplikat terdeteksi di level primary/unique constraint
        return None, True

def claim_next_pending_job(db_path: Path, project_id: str) -> Optional[Dict[str, Any]]:
    """
    Klaim pekerjaan PENDING tertua secara atomik menggunakan BEGIN IMMEDIATE transaction.
    Menjamin dua thread/worker tidak pernah mengklaim job yang sama (race condition prevention).
    """
    if not db_path.exists():
        return None
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        conn.isolation_level = None  # Manual transaction control
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE;")
        cur.execute("""
            SELECT id, project_id, event_id, issue_key, runner_target, created_at
            FROM webhook_jobs
            WHERE project_id = ? AND status = 'PENDING'
            ORDER BY id ASC
            LIMIT 1;
        """, (project_id,))
        row = cur.fetchone()
        if not row:
            cur.execute("COMMIT;")
            return None

        job_id = row[0]
        cur.execute("""
            UPDATE webhook_jobs
            SET status = 'RUNNING', updated_at = ?
            WHERE id = ?;
        """, (now_iso, job_id))
        cur.execute("COMMIT;")
        return {
            "id": row[0],
            "project_id": row[1],
            "event_id": row[2],
            "issue_key": row[3],
            "runner_target": row[4],
            "created_at": row[5]
        }

def mark_job_status(db_path: Path, job_id: int, status: str, error_message: Optional[str] = None):
    """Memperbarui status pekerjaan secara durable."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        conn.execute("""
            UPDATE webhook_jobs
            SET status = ?, error_message = ?, updated_at = ?
            WHERE id = ?;
        """, (status, error_message, now_iso, job_id))
        conn.commit()
