import os
import re
import json
import base64
import urllib.request
import urllib.error
import mimetypes
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Menolak seluruh redirect HTTP untuk mencegah kebocoran kredensial atau payload."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.get_full_url(), code, f"HTTP redirect [{code}] ditolak untuk endpoint API Jira", headers, fp)

class JiraClient:
    """Klien REST API Jira Cloud terisolasi menggunakan library bawaan urllib."""

    def __init__(self, base_url: str, email: str, api_token: str, timeout: int = 30):
        if not base_url or not email or not api_token:
            raise ValueError("JiraClient membutuhkan base_url, email, dan api_token yang tidak kosong.")

        p = urllib.parse.urlparse(base_url)
        if p.scheme != "https":
            raise ValueError(f"Jira base_url wajib menggunakan protokol HTTPS. Ditemukan: '{base_url}'")
        if "@" in p.netloc:
            raise ValueError("Userinfo/kredensial dilarang dicantumkan di dalam URL base_url.")
        if p.query or p.fragment:
            raise ValueError("Base URL Jira dilarang memuat query string atau fragment.")
        
        self.base_url = f"{p.scheme}://{p.netloc}"
        self.email = email
        self.api_token = api_token
        self.timeout = timeout
        
        auth_str = f"{self.email}:{self.api_token}"
        self.auth_header = f"Basic {base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')}"
        self.opener = urllib.request.build_opener(NoRedirectHandler)

    def _validate_issue_key(self, issue_key: str) -> str:
        clean = issue_key.strip().upper()
        if not re.match(r'^[A-Z0-9]+-\d+$', clean):
            raise ValueError(f"Format issue key '{issue_key}' tidak valid. Diharapkan format seperti 'PROJ-123'.")
        return clean

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
            with self.opener.open(req, timeout=self.timeout) as resp:
                resp_bytes = resp.read()
                if not resp_bytes:
                    return {}
                return json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Masking error agar tidak mengekspos token/rahasia ke log
            raise RuntimeError(f"Jira API Error [{e.code}] on {method} {endpoint}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Jira Connection Error on {method} {endpoint}: {str(e)}")

    def get_issue(self, issue_key: str) -> Dict[str, Any]:
        """Mengambil data tiket Jira (summary, description, status, project)."""
        clean_key = self._validate_issue_key(issue_key)
        return self._request("GET", f"/rest/api/2/issue/{clean_key}?fields=summary,description,status,project")

    def post_comment(self, issue_key: str, comment_text: str) -> Dict[str, Any]:
        """Menambahkan komentar ke tiket Jira."""
        clean_key = self._validate_issue_key(issue_key)
        payload = json.dumps({"body": comment_text}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        return self._request("POST", f"/rest/api/2/issue/{clean_key}/comment", data=payload, headers=headers)

    def attach_file(self, issue_key: str, file_path: Path) -> List[Dict[str, Any]]:
        """Mengunggah file lampiran (attachment) ke tiket Jira dengan multipart/form-data."""
        clean_key = self._validate_issue_key(issue_key)
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
    Mengekstrak referensi kasus uji (misal: TC-001) HANYA dari bagian 'Test Cases' pada deskripsi tiket.
    Fail-closed:
    - Heading 'Test Cases' terikat pada awal baris (mencegah salah deteksi di tengah kalimat).
    - Berhenti pada heading berikutnya.
    - Urutan kemunculan dipertahankan, deduplikasi case-insensitive.
    - Setiap ID wajib menemukan tepat 1 berkas yang cocok di test_cases_dir.
    """
    # Heading terikat awal baris
    m_section = re.search(r'(?:^|\n)\s*(?:###?\s*Test\s+Cases|h[1-6]\.\s*Test\s+Cases|Test\s+Cases\s*:?)(.*?)(?=(?:\n\s*###?|\n\s*h[1-6]\.|$))', description_text, re.DOTALL | re.IGNORECASE)
    if not m_section:
        return []

    if not test_cases_dir.exists():
        raise FileNotFoundError(f"Direktori kasus uji '{test_cases_dir}' tidak ditemukan pada proyek ini.")

    search_target = m_section.group(1)
    raw_matches = re.findall(r'\b(TC-\d+)\b', search_target, re.IGNORECASE)
    seen = set()
    ordered_ids = []
    for tc in raw_matches:
        u = tc.upper()
        if u not in seen:
            seen.add(u)
            ordered_ids.append(u)

    matched_files: List[Path] = []
    for pattern_id in ordered_ids:
        candidates = [
            f for f in test_cases_dir.glob("*.md")
            if f.name.upper().startswith(f"{pattern_id}-") or f.name.upper() == f"{pattern_id}.MD"
        ]
        if len(candidates) == 1:
            matched_files.append(candidates[0])
        elif len(candidates) > 1:
            raise ValueError(
                f"Referensi ambigu untuk '{pattern_id}': ditemukan {len(candidates)} file yang cocok "
                f"({[c.name for c in candidates]}). Pastikan penamaan file unik."
            )
        else:
            raise FileNotFoundError(f"Berkas untuk kasus uji '{pattern_id}' tidak ditemukan di {test_cases_dir}.")

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

    if verdict == "PASSED":
        badge = "(/) *PASSED*"
    elif verdict == "BLOCKED":
        badge = "(-) *BLOCKED*"
    elif verdict == "ERROR":
        badge = "(!) *ERROR*"
    else:
        badge = "(x) *FAILED*"

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


def publish_jira_artifacts(run_id: str, issue_key: str, client: JiraClient, project_root: Path, drive_info: dict = None, force: bool = False) -> Dict[str, Any]:
    """
    Mempublikasikan artefak pengujian (DOCX, video) dan komentar ke tiket Jira secara idempoten.
    - Menolak perpindahan target tenant atau tiket yang berbeda dari publikasi sebelumnya.
    - Menyimpan ID attachment dan komentar segera ke metadata.json setelah setiap aksi.
    - Retry tidak menduplikasi file yang sudah berhasil diunggah sebelumnya.
    """
    if not re.match(r'^[A-Za-z0-9_-]+$', run_id):
        raise ValueError(f"Format run_id '{run_id}' tidak valid (hanya karakter alfanumerik, dash, dan underscore).")

    safe_run_id = run_id
    run_dir = project_root / "artifacts" / safe_run_id
    meta_path = run_dir / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"metadata.json untuk {safe_run_id} tidak ditemukan di {project_root}.")

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # 1. Simpan binding tenant & issue_key segera sebelum request jaringan pertama
    target_tenant = client.base_url
    clean_key = client._validate_issue_key(issue_key)

    jira_status = meta.setdefault("jira_publish_status", {
        "tenant": target_tenant,
        "issue_key": clean_key,
        "published": False,
        "attachments": {},
        "comment_id": None
    })

    # Verifikasi destination binding agar run tidak salah publikasi ke tiket/tenant lain
    saved_tenant = jira_status.get("tenant")
    saved_key = jira_status.get("issue_key")
    if saved_tenant and saved_tenant != target_tenant:
        raise ValueError(f"Target tenant mismatch: run ini sebelumnya ditautkan ke '{saved_tenant}', bukan '{target_tenant}'.")
    if saved_key and saved_key != clean_key:
        raise ValueError(f"Target issue key mismatch: run ini sebelumnya ditautkan ke '{saved_key}', bukan '{clean_key}'.")

    jira_status["tenant"] = target_tenant
    jira_status["issue_key"] = clean_key
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    if jira_status.get("published") and not force:
        return jira_status

    docx_path = run_dir / "report.docx"
    video_path = run_dir / "evidence.webm"

    # Verifikasi integritas artefak: laporan wajib ada
    if not docx_path.exists():
        raise FileNotFoundError(f"Laporan report.docx tidak ditemukan di {run_dir}. Publikasi dibatalkan.")

    # Jika metadata mencatat file video, pastikan file rekaman ada di disk
    if meta.get("artifacts", {}).get("video") and not video_path.exists():
        raise FileNotFoundError(f"Berkas video bukti yang tercatat di metadata tidak ditemukan di {video_path}.")

    # 2. Upload DOCX jika belum tercatat di status
    docx_name = docx_path.name
    if docx_name not in jira_status["attachments"] or force:
        att_docx = client.attach_file(issue_key, docx_path)
        if not att_docx or not att_docx[0].get("id"):
            raise RuntimeError(f"Gagal mengunggah attachment {docx_name}: respons Jira tidak memuat ID file.")
        jira_status["attachments"][docx_name] = att_docx[0].get("id")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    # 3. Upload Video jika ada dan belum tercatat di status
    if video_path.exists():
        video_name = video_path.name
        if video_name not in jira_status["attachments"] or force:
            att_vid = client.attach_file(issue_key, video_path)
            if not att_vid or not att_vid[0].get("id"):
                raise RuntimeError(f"Gagal mengunggah attachment {video_name}: respons Jira tidak memuat ID file.")
            jira_status["attachments"][video_name] = att_vid[0].get("id")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

    # 4. Post Komentar Ringkasan jika belum pernah diposting
    if not jira_status.get("comment_id") or force:
        attachment_summary = [{"filename": k} for k in jira_status["attachments"].keys()]
        comment_body = format_jira_verdict_comment(meta, attachment_summary, drive_info)
        res_cmt = client.post_comment(issue_key, comment_body)
        if not res_cmt or not res_cmt.get("id"):
            raise RuntimeError("Gagal memposting komentar ke Jira: respons Jira tidak memuat ID komentar.")
        jira_status["comment_id"] = res_cmt.get("id")

    jira_status["published"] = True
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return jira_status
