import os
import re
import json
import hmac
import hashlib
import logging
import threading
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any, Optional

from runner.config import load_project_config, load_project_env
from runner.adapters.job_queue import (
    get_db_path,
    enqueue_job,
    claim_next_pending_job,
    mark_job_status,
    reconcile_interrupted_jobs_on_startup
)

logger = logging.getLogger("saqa.webhook")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MAX_PAYLOAD_SIZE = 1024 * 1024  # 1 MiB max
_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP_EVENT = threading.Event()

def extract_issue_key_from_payload(payload: dict) -> Optional[str]:
    """
    Mengekstrak Issue Key secara fleksibel dari berbagai bentuk payload Jira:
    - Jira Cloud Automation custom data: payload.get('issue_key') atau payload.get('client_payload', {}).get('issue_key')
    - Native Jira Webhook: payload.get('issue', {}).get('key')
    """
    candidates = [
        payload.get("issue_key"),
        payload.get("client_payload", {}).get("issue_key") if isinstance(payload.get("client_payload"), dict) else None,
        payload.get("issue", {}).get("key") if isinstance(payload.get("issue"), dict) else None,
    ]
    for c in candidates:
        if c and isinstance(c, str):
            clean = c.strip().upper()
            if re.match(r'^[A-Z0-9]+-[0-9]+$', clean):
                return clean
    return None

def extract_status_from_payload(payload: dict) -> Optional[str]:
    """Mengekstrak nama status perpindahan tiket jika tersedia di payload."""
    candidates = [
        payload.get("status"),
        payload.get("issue", {}).get("fields", {}).get("status", {}).get("name") if isinstance(payload.get("issue"), dict) else None,
        payload.get("transition", {}).get("to_status") if isinstance(payload.get("transition"), dict) else None,
    ]
    for s in candidates:
        if s and isinstance(s, str):
            return s.strip()
    return None

def extract_event_id_from_payload(payload: dict, raw_body: bytes) -> str:
    """Mengekstrak event_id dari payload atau menghasilkan hash kanonikal dari body jika tidak disediakan."""
    candidates = [
        payload.get("event_id"),
        payload.get("timestamp"),
        payload.get("webhookEventId"),
    ]
    for eid in candidates:
        if eid:
            return str(eid).strip()
    # Fallback deterministik: hash dari payload body
    return hashlib.sha256(raw_body).hexdigest()[:32]

def dispatch_github_actions(issue_key: str, env_vars: dict) -> Dict[str, Any]:
    """Memicu repository_dispatch pada GitHub Actions."""
    repo = env_vars.get("GITHUB_REPO", "").strip()
    token = env_vars.get("GITHUB_PAT", env_vars.get("GITHUB_TOKEN", "")).strip()

    if not repo or not token:
        raise ValueError("GITHUB_REPO dan GITHUB_PAT wajib disetel untuk runner_target: 'github'.")

    url = f"https://api.github.com/repos/{repo}/dispatches"
    payload = json.dumps({
        "event_type": "jira-trigger",
        "client_payload": {"issue_key": issue_key}
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "User-Agent": "SAQA-Webhook-Server"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return {"status": "dispatched", "target": "github", "code": resp.status}

def dispatch_gitlab_ci(issue_key: str, env_vars: dict) -> Dict[str, Any]:
    """Memicu Pipeline Trigger API pada GitLab CI."""
    gitlab_url = env_vars.get("GITLAB_BASE_URL", "https://gitlab.com").rstrip("/")
    project_id = env_vars.get("GITLAB_PROJECT_ID", "").strip()
    token = env_vars.get("GITLAB_TRIGGER_TOKEN", "").strip()
    ref = env_vars.get("GITLAB_REF", "main").strip()

    if not project_id or not token:
        raise ValueError("GITLAB_PROJECT_ID dan GITLAB_TRIGGER_TOKEN wajib disetel untuk runner_target: 'gitlab'.")

    url = f"{gitlab_url}/api/v4/projects/{project_id}/trigger/pipeline"
    payload = json.dumps({
        "token": token,
        "ref": ref,
        "variables": {"ISSUE_KEY": issue_key}
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "SAQA-Webhook-Server"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return {"status": "dispatched", "target": "gitlab", "code": resp.status}

def process_job_execution(job: dict, project_root: Path):
    """Mengeksekusi satu pekerjaan dari antrean secara terisolasi."""
    db_path = get_db_path(project_root)
    job_id = job["id"]
    issue_key = job["issue_key"]
    runner = job["runner_target"]
    env_vars = load_project_env(project_root)

    logger.info(f"🚀 [Worker] Memproses Job #{job_id} ({issue_key}) via {runner}...")

    try:
        if runner == "local":
            from cli import cmd_jira_process
            import argparse
            args = argparse.Namespace(issue_key=issue_key, project_root=str(project_root), no_publish=False)
            ret = cmd_jira_process(args)
            if ret == 0:
                mark_job_status(db_path, job_id, "COMPLETED")
                logger.info(f"✅ [Worker] Job #{job_id} ({issue_key}) selesai sukses.")
            else:
                mark_job_status(db_path, job_id, "FAILED", error_message="Eksekusi return code non-zero.")
                logger.warning(f"⚠️ [Worker] Job #{job_id} ({issue_key}) selesai dengan status FAILED.")
        elif runner == "github":
            dispatch_github_actions(issue_key, env_vars)
            mark_job_status(db_path, job_id, "DISPATCHED")
            logger.info(f"✅ [Worker] Job #{job_id} dispatched ke GitHub Actions.")
        elif runner == "gitlab":
            dispatch_gitlab_ci(issue_key, env_vars)
            mark_job_status(db_path, job_id, "DISPATCHED")
            logger.info(f"✅ [Worker] Job #{job_id} dispatched ke GitLab CI.")
    except Exception as e:
        logger.error(f"❌ [Worker] Job #{job_id} ({issue_key}) error: {str(e)}")
        mark_job_status(db_path, job_id, "NEEDS_RECONCILIATION", error_message=str(e))

def queue_worker_loop(project_root: Path, stop_event: threading.Event):
    """Loop worker latar belakang yang memproses antrean SQLite secara serial."""
    db_path = get_db_path(project_root)
    cfg = load_project_config(project_root)
    project_id = cfg.get("project_id", project_root.name)

    while not stop_event.is_set():
        try:
            job = claim_next_pending_job(db_path, project_id)
            if job:
                process_job_execution(job, project_root)
            else:
                stop_event.wait(timeout=1.0)
        except Exception as e:
            logger.error(f"Worker queue loop error: {e}")
            stop_event.wait(timeout=2.0)


class SaqaWebhookHandler(BaseHTTPRequestHandler):
    project_root: Path = Path.cwd()
    runner_override: Optional[str] = None
    allow_unauthenticated: bool = False

    def _send_json(self, status_code: int, data: dict):
        resp_bytes = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)

    def do_GET(self):
        if self.path in ["/health", "/"]:
            cfg = load_project_config(self.project_root)
            runner = self.runner_override or cfg.get("runner_target", "local")
            self._send_json(200, {
                "status": "ok",
                "service": "saqa-webhook-receiver",
                "project_id": cfg.get("project_id"),
                "runner_target": runner,
            })
        else:
            self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        if self.path not in ["/jira-webhook", "/webhook", "/webhook/jira"]:
            self._send_json(404, {"error": f"Endpoint '{self.path}' tidak dikenal."})
            return

        cfg = load_project_config(self.project_root)
        env_vars = load_project_env(self.project_root)
        project_id = cfg.get("project_id", self.project_root.name)
        db_path = get_db_path(self.project_root)

        # 1. Autentikasi Secret Token (Timing-Safe & Fail-Closed)
        expected_secret = env_vars.get("WEBHOOK_SECRET", "").strip()
        if not expected_secret and not self.allow_unauthenticated:
            logger.error("Konfigurasi server tidak aman: WEBHOOK_SECRET belum disetel di .env.")
            self._send_json(500, {
                "error": "Server Configuration Error: WEBHOOK_SECRET wajib disetel di .env untuk mengamankan webhook."
            })
            return

        if expected_secret:
            incoming_secret = self.headers.get("X-Webhook-Secret", "").strip()
            auth_header = self.headers.get("Authorization", "").strip()
            if not incoming_secret and auth_header.startswith("Bearer "):
                incoming_secret = auth_header.split("Bearer ", 1)[1].strip()

            if not hmac.compare_digest(incoming_secret.encode("utf-8"), expected_secret.encode("utf-8")):
                logger.warning("Permintaan ditolak: Secret token tidak cocok.")
                self._send_json(401, {"error": "Unauthorized: Webhook secret invalid."})
                return

        # 2. Batas ukuran payload (Max 1 MiB)
        try:
            content_len_header = self.headers.get("Content-Length")
            if not content_len_header:
                self._send_json(411, {"error": "Length Required: Header Content-Length wajib disertakan."})
                return

            content_len = int(content_len_header)
            if content_len <= 0:
                self._send_json(400, {"error": "Body JSON kosong."})
                return
            if content_len > MAX_PAYLOAD_SIZE:
                self._send_json(413, {"error": f"Payload terlalu besar (maksimal {MAX_PAYLOAD_SIZE} bytes)."})
                return

            body_bytes = self.rfile.read(content_len)
            payload = json.loads(body_bytes.decode("utf-8"))
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "Format payload wajib berupa JSON Object."})
                return
        except Exception as e:
            self._send_json(400, {"error": f"Payload bukan JSON valid: {str(e)}"})
            return

        # 3. Ekstraksi Issue Key
        issue_key = extract_issue_key_from_payload(payload)
        if not issue_key:
            self._send_json(400, {"error": "Issue key tidak ditemukan atau formatnya tidak valid (misal: MED-101)."})
            return

        # 4. Validasi Allowlist Project Key
        allowed_keys = cfg.get("environment", {}).get("project_keys", [])
        if allowed_keys:
            proj_prefix = issue_key.split("-")[0]
            if proj_prefix not in allowed_keys:
                self._send_json(403, {"error": f"Project key '{proj_prefix}' di luar allowlist proyek: {allowed_keys}"})
                return

        # 5. Filter status pemicu (trigger_statuses)
        incoming_status = extract_status_from_payload(payload)
        trigger_statuses = cfg.get("input", {}).get("trigger_statuses", [])
        if incoming_status and trigger_statuses:
            matched = any(incoming_status.strip().lower() == s.strip().lower() for s in trigger_statuses)
            if not matched:
                logger.info(f"Tiket {issue_key} berstatus '{incoming_status}'. Tidak cocok dengan trigger_statuses: {trigger_statuses}. Dilewati.")
                self._send_json(200, {
                    "status": "skipped",
                    "issue_key": issue_key,
                    "reason": f"Status '{incoming_status}' tidak terdaftar pada trigger_statuses."
                })
                return

        # 6. Tentukan Runner Target & Enqueue Job secara Durable
        runner = self.runner_override or cfg.get("runner_target", "local")
        event_id = extract_event_id_from_payload(payload, body_bytes)

        job_id, is_duplicate = enqueue_job(db_path, project_id, event_id, issue_key, runner)
        if is_duplicate:
            logger.info(f"Event ID {event_id} sudah pernah tercatat sebelumnya. Mengabaikan event duplikat.")
            self._send_json(200, {
                "status": "duplicate_event",
                "event_id": event_id,
                "issue_key": issue_key,
                "message": "Event ID ini sudah pernah diproses."
            })
            return

        logger.info(f"📥 Enqueued Job #{job_id} untuk {issue_key} via {runner}. Mengembalikan HTTP 202.")
        self._send_json(202, {
            "status": "accepted",
            "job_id": job_id,
            "event_id": event_id,
            "issue_key": issue_key,
            "runner": runner,
            "message": "Pekerjaan pengujian berhasil disimpan di antrean durable."
        })


def start_webhook_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    project_root: Path = None,
    runner_override: Optional[str] = None,
    allow_unauthenticated: bool = False
):
    """Menjalankan server webhook HTTP dengan worker antrean durable SQLite."""
    global _WORKER_THREAD, _WORKER_STOP_EVENT

    if project_root is None:
        project_root = Path.cwd()
    project_root = Path(project_root).resolve()

    # Preflight check: tolak startup jika WEBHOOK_SECRET tidak ada dan allow_unauthenticated=False
    env_vars = load_project_env(project_root)
    if not env_vars.get("WEBHOOK_SECRET") and not allow_unauthenticated:
        raise ValueError(
            "WEBHOOK_SECRET wajib disetel di .env proyek untuk menjalankan server webhook secara aman. "
            "Gunakan flag --allow-unauthenticated jika hanya ingin pengujian lokal tanpa autentikasi."
        )

    db_path = get_db_path(project_root)
    cfg = load_project_config(project_root)
    project_id = cfg.get("project_id", project_root.name)

    # Reconcile job yang terinterupsi saat restart sebelumnya
    reconcile_interrupted_jobs_on_startup(db_path, project_id)

    class CustomHandler(SaqaWebhookHandler):
        pass
    CustomHandler.project_root = project_root
    CustomHandler.runner_override = runner_override
    CustomHandler.allow_unauthenticated = allow_unauthenticated

    # Jalankan background worker untuk memproses antrean SQLite
    _WORKER_STOP_EVENT.clear()
    _WORKER_THREAD = threading.Thread(target=queue_worker_loop, args=(project_root, _WORKER_STOP_EVENT), daemon=True)
    _WORKER_THREAD.start()

    server_address = (host, port)
    httpd = HTTPServer(server_address, CustomHandler)
    logger.info(f"🌐 [SAQA Webhook Server] Mendengarkan di http://{host}:{port}/jira-webhook")
    logger.info(f"📁 Project Root: {project_root}")
    logger.info(f"⚙️  Default Runner: {runner_override or 'from saqa.json'}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nServer webhook dihentikan.")
    finally:
        _WORKER_STOP_EVENT.set()
        httpd.server_close()
