import os
import re
import json
import logging
import threading
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any, Optional, Set

from runner.config import load_project_config, load_project_env

logger = logging.getLogger("saqa.webhook")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

_ACTIVE_LOCK = threading.Lock()
_ACTIVE_ISSUES: Set[str] = set()

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

def run_local_jira_worker(issue_key: str, project_root: Path):
    """Menjalankan engine pengujian secara lokal di background worker."""
    with _ACTIVE_LOCK:
        _ACTIVE_ISSUES.add(issue_key)

    logger.info(f"🚀 [Worker] Memulai eksekusi lokal untuk tiket Jira: {issue_key}")
    try:
        from cli import cmd_jira_process
        import argparse
        args = argparse.Namespace(issue_key=issue_key, project_root=str(project_root), no_publish=False)
        cmd_jira_process(args)
    except Exception as e:
        logger.error(f"❌ [Worker] Error saat memproses {issue_key}: {str(e)}")
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_ISSUES.discard(issue_key)
        logger.info(f"🏁 [Worker] Selesai memproses tiket {issue_key}.")


class SaqaWebhookHandler(BaseHTTPRequestHandler):
    project_root: Path = Path.cwd()
    runner_override: Optional[str] = None

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
            with _ACTIVE_LOCK:
                active_count = len(_ACTIVE_ISSUES)
            self._send_json(200, {
                "status": "ok",
                "service": "saqa-webhook-receiver",
                "project_id": cfg.get("project_id"),
                "runner_target": runner,
                "active_jobs": active_count
            })
        else:
            self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        if self.path not in ["/jira-webhook", "/webhook", "/webhook/jira"]:
            self._send_json(404, {"error": f"Endpoint '{self.path}' tidak dikenal."})
            return

        cfg = load_project_config(self.project_root)
        env_vars = load_project_env(self.project_root)

        # 1. Verifikasi secret token jika disetel (WEBHOOK_SECRET)
        expected_secret = env_vars.get("WEBHOOK_SECRET", "").strip()
        if expected_secret:
            incoming_secret = self.headers.get("X-Webhook-Secret", "").strip()
            auth_header = self.headers.get("Authorization", "").strip()
            if not incoming_secret and auth_header.startswith("Bearer "):
                incoming_secret = auth_header.split("Bearer ", 1)[1].strip()

            if incoming_secret != expected_secret:
                logger.warning("Permintaan ditolak: Secret token tidak cocok.")
                self._send_json(401, {"error": "Unauthorized: Webhook secret invalid."})
                return

        # 2. Baca body JSON
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len == 0:
                self._send_json(400, {"error": "Body JSON kosong."})
                return
            body_bytes = self.rfile.read(content_len)
            payload = json.loads(body_bytes.decode("utf-8"))
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

        # 6. Cek deduplikasi in-flight
        with _ACTIVE_LOCK:
            if issue_key in _ACTIVE_ISSUES:
                logger.info(f"Tiket {issue_key} sedang berjalan saat ini. Mengabaikan event duplikat.")
                self._send_json(200, {
                    "status": "already_running",
                    "issue_key": issue_key,
                    "message": "Pengujian untuk tiket ini sedang berlangsung."
                })
                return

        # 7. Tentukan Runner Target (local, github, gitlab)
        runner = self.runner_override or cfg.get("runner_target", "local")

        logger.info(f"📥 Menerima event Jira untuk {issue_key}. Target Runner: {runner}")

        if runner == "local":
            # Jalankan worker di background thread agar response HTTP 202 langsung kembali ke Jira
            t = threading.Thread(target=run_local_jira_worker, args=(issue_key, self.project_root), daemon=True)
            t.start()
            self._send_json(202, {
                "status": "accepted",
                "issue_key": issue_key,
                "runner": "local",
                "message": "Pengujian diterima dan sedang dieksekusi di server lokal."
            })
        elif runner == "github":
            try:
                res_gh = dispatch_github_actions(issue_key, env_vars)
                self._send_json(202, {
                    "status": "dispatched",
                    "issue_key": issue_key,
                    "runner": "github",
                    "dispatch_response": res_gh
                })
            except Exception as e_gh:
                logger.error(f"Gagal memicu GitHub Actions: {e_gh}")
                self._send_json(500, {"error": f"Gagal dispatch ke GitHub Actions: {str(e_gh)}"})
        elif runner == "gitlab":
            try:
                res_gl = dispatch_gitlab_ci(issue_key, env_vars)
                self._send_json(202, {
                    "status": "dispatched",
                    "issue_key": issue_key,
                    "runner": "gitlab",
                    "dispatch_response": res_gl
                })
            except Exception as e_gl:
                logger.error(f"Gagal memicu GitLab CI: {e_gl}")
                self._send_json(500, {"error": f"Gagal dispatch ke GitLab CI: {str(e_gl)}"})
        else:
            self._send_json(400, {"error": f"Runner target '{runner}' tidak didukung."})


def start_webhook_server(host: str = "0.0.0.0", port: int = 8080, project_root: Path = None, runner_override: Optional[str] = None):
    """Menjalankan server webhook HTTP."""
    if project_root is None:
        project_root = Path.cwd()
    project_root = Path(project_root).resolve()

    class CustomHandler(SaqaWebhookHandler):
        pass
    CustomHandler.project_root = project_root
    CustomHandler.runner_override = runner_override

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
        httpd.server_close()
