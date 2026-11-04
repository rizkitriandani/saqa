import os
import re
import json
import base64
import urllib.request
import urllib.error
import mimetypes
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

class JiraClient:
    """Klien REST API Jira Cloud terisolasi menggunakan library bawaan urllib."""

    def __init__(self, base_url: str, email: str, api_token: str, timeout: int = 30):
        if not base_url or not email or not api_token:
            raise ValueError("JiraClient membutuhkan base_url, email, dan api_token yang tidak kosong.")
        
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.api_token = api_token
        self.timeout = timeout
        
        # Header Basic Authentication
        auth_str = f"{self.email}:{self.api_token}"
        self.auth_header = f"Basic {base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')}"

    def _request(self, method: str, endpoint: str, data: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        req_headers = {
            "Authorization": self.auth_header,
            "Accept": "application/json"
        }
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_bytes = resp.read()
                if not resp_bytes:
                    return {}
                return json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else ""
            raise RuntimeError(f"Jira API Error [{e.code}] on {method} {endpoint}: {err_body}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Jira Connection Error on {method} {endpoint}: {str(e)}")

    def get_issue(self, issue_key: str) -> Dict[str, Any]:
        """Mengambil data tiket Jira (summary, description, status, project)."""
        clean_key = issue_key.strip().upper()
        return self._request("GET", f"/rest/api/2/issue/{clean_key}?fields=summary,description,status,project")

    def post_comment(self, issue_key: str, comment_text: str) -> Dict[str, Any]:
        """Menambahkan komentar ke tiket Jira."""
        clean_key = issue_key.strip().upper()
        payload = json.dumps({"body": comment_text}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        return self._request("POST", f"/rest/api/2/issue/{clean_key}/comment", data=payload, headers=headers)

    def attach_file(self, issue_key: str, file_path: Path) -> List[Dict[str, Any]]:
        """Mengunggah file lampiran (attachment) ke tiket Jira dengan multipart/form-data."""
        clean_key = issue_key.strip().upper()
        if not file_path.exists():
            raise FileNotFoundError(f"File attachment tidak ditemukan: {file_path}")

        boundary = "----WebKitFormBoundarySAQAPlaywright" + base64.b64encode(os.urandom(8)).decode("ascii").replace("=", "")
        filename = file_path.name
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        headers = {
            "X-Atlassian-Token": "no-check",
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        }
        return self._request("POST", f"/rest/api/2/issue/{clean_key}/attachments", data=body, headers=headers)


def extract_text_from_description(raw_desc: Any) -> str:
    """
    Mengekstrak teks murni dari field description Jira.
    Mendukung format string (v2) dan format Atlassian Document Format (ADF v3).
    """
    if not raw_desc:
        return ""
    if isinstance(raw_desc, str):
        return raw_desc

    if isinstance(raw_desc, dict) and raw_desc.get("type") == "doc":
        chunks = []
        def walk(node):
            if isinstance(node, dict):
                ntype = node.get("type")
                if ntype == "text":
                    chunks.append(node.get("text", ""))
                elif ntype == "heading":
                    chunks.append("\n\n### ")
                elif ntype in ["paragraph", "listItem"]:
                    chunks.append("\n")
                for child in node.get("content", []):
                    walk(child)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(raw_desc)
        return "".join(chunks).strip()

    return str(raw_desc)


def extract_test_case_references(description_text: str, test_cases_dir: Path) -> List[Path]:
    """
    Mengekstrak referensi kasus uji (misal: TC-001) dari teks deskripsi tiket.
    Fail-closed:
    - Setiap referensi wajib menemukan tepat 1 berkas yang cocok di test_cases_dir.
    - Jika ada lebih dari 1 berkas yang cocok (ambigu), melempar ValueError.
    - Jika berkas tidak ditemukan, melempar FileNotFoundError.
    """
    if not test_cases_dir.exists():
        raise FileNotFoundError(f"Direktori kasus uji tidak ditemukan: {test_cases_dir}")

    # Pola ID: TC-xxx (contoh: TC-001, TC-999)
    matches = sorted(list(set(re.findall(r'\b(TC-\d+)\b', description_text, re.IGNORECASE))))
    matched_files: List[Path] = []

    for tc_id in matches:
        pattern_id = tc_id.upper()
        candidates = [
            f for f in test_cases_dir.glob("*.md")
            if f.name.upper().startswith(f"{pattern_id}-") or f.name.upper() == f"{pattern_id}.MD"
        ]
        if len(candidates) == 1:
            matched_files.append(candidates[0])
        elif len(candidates) > 1:
            raise ValueError(
                f"Referensi ambigu untuk '{tc_id}': ditemukan {len(candidates)} file yang cocok "
                f"({[c.name for c in candidates]}). Pastikan penamaan file unik."
            )
        else:
            raise FileNotFoundError(f"Berkas untuk kasus uji '{tc_id}' tidak ditemukan di {test_cases_dir}.")

    return matched_files


def extract_qa_scenario_block(description_text: str) -> Optional[str]:
    """
    Mengekstrak blok skenario bahasa alami di bawah heading 'QA Scenario' pada deskripsi tiket.
    """
    m = re.search(r'(?:###?\s*QA\s+Scenario|h[1-6]\.\s*QA\s+Scenario)(.*?)(?=(?:###?\s*|h[1-6]\.\s*|$))', description_text, re.DOTALL | re.IGNORECASE)
    if m:
        scenario = m.group(1).strip()
        if scenario:
            return scenario
    return None


def format_jira_verdict_comment(meta: dict, attachments: list, drive_info: dict = None) -> str:
    """Memformat komentar markdown untuk diposting kembali ke tiket Jira."""
    verdict = meta.get("verdict", "UNKNOWN")
    tc_id = meta.get("test_case_id", "-")
    title = meta.get("title", "-")
    dur = meta.get("execution_duration_seconds", "-")
    actual = meta.get("actual_result", meta.get("error_message", "-"))

    badge = "(/) *PASSED*" if verdict == "PASSED" else "(-)" if verdict == "BLOCKED" else "(x) *FAILED*"

    lines = [
        f"h3. [SAQA Execution Report] {badge}",
        f"* *Test Case*: {tc_id} - {title}",
        f"* *Verdict*: {verdict}",
        f"* *Duration*: {dur} seconds",
        f"* *Details*: {actual}",
        "",
        "h4. Bukti Hasil Pengujian (Attachments):"
    ]

    if attachments:
        for att in attachments:
            fname = att.get("filename", "")
            lines.append(f"* [^{fname}] (Terlampir pada tiket ini)")
    else:
        lines.append("* _Tidak ada file attachment baru yang diunggah._")

    if drive_info and drive_info.get("published"):
        lines.append("")
        lines.append("h4. Tautan Google Workspace:")
        if drive_info.get("google_doc_url"):
            lines.append(f"* [Google Docs Laporan|{drive_info.get('google_doc_url')}]")
        if drive_info.get("google_video_url"):
            lines.append(f"* [Rekaman Video Drive|{drive_info.get('google_video_url')}]")

    lines.append("")
    lines.append(f"_Dijalankan secara otomatis oleh SAQA Engine pada {meta.get('timestamp')}_")
    return "\n".join(lines)
