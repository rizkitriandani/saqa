import re
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Security: Hanya environment variables terdaftar yang boleh disubstitusi ke langkah peramban
ALLOWED_ENV_VARS = {"DEV_BASE_URL", "QA_USERNAME", "QA_PASSWORD"}

def compute_canonical_content_hash(content: str) -> str:
    """
    Menghitung SHA-256 hash dari konten kanonikal kasus uji.
    Baris metadata 'Approval Status' dan 'Approval Hash' dikecualikan dari kalkulasi
    sehingga penandatanganan tidak mengubah hash konten yang diaudit.
    """
    canonical_lines = []
    for line in content.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("- **Approval Status**:") or trimmed.startswith("- **Approval Hash**:"):
            continue
        canonical_lines.append(line.rstrip())

    # Gabungkan dengan newline konsisten
    canonical_text = "\n".join(canonical_lines).strip()
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()

def compile_expected_results(expected_results: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Menerjemahkan kriteria hasil Expected Results menjadi aturan asersi terstruktur yang dapat dievaluasi mesin.
    Prinsip Fail-Closed:
    - Wajib menggunakan re.fullmatch agar tidak ada trailing text atau klausa gabungan yang lolos tanpa evaluasi.
    - Wajib menggunakan tanda kutip eksplisit ("..." atau '...') dengan isi tidak kosong.
    - Sintaks parsial, klausa gabungan ('and ...'), atau narasi bebas dikembalikan dalam unparseable_rules
      sehingga eksekusi dibatalkan sebelum browser berjalan.
    """
    compiled_rules: List[Dict[str, Any]] = []
    unparseable_rules: List[str] = []

    # Gramar baku fullmatch: ^<pola>\s+["']<nilai>["']$
    # Mendukung kutip tunggal di dalam kutip ganda atau sebaliknya (misal: element "button[type='submit']" is visible)
    patterns = [
        ("url_not_contains", re.compile(r'^url\s+(?:does\s+not\s+contain|not\s+contains?)\s+(?:"([^"]+)"|\'([^\']+)\')$', re.IGNORECASE)),
        ("url_contains", re.compile(r'^url\s+contains?\s+(?:"([^"]+)"|\'([^\']+)\')$', re.IGNORECASE)),
        ("url_equals", re.compile(r'^url\s+equals?\s+(?:"([^"]+)"|\'([^\']+)\')$', re.IGNORECASE)),
        ("heading_contains", re.compile(r'^heading\s+contains?\s+(?:"([^"]+)"|\'([^\']+)\')$', re.IGNORECASE)),
        ("text_contains", re.compile(r'^(?:text|page|body)\s+contains?\s+(?:"([^"]+)"|\'([^\']+)\')$', re.IGNORECASE)),
        ("element_visible", re.compile(r'^element\s+(?:"([^"]+)"|\'([^\']+)\')\s+is\s+visible$', re.IGNORECASE)),
    ]

    for raw in expected_results:
        clean = raw.strip().strip("- *").strip()
        if not clean:
            continue

        matched = False
        for rule_type, pattern in patterns:
            m = pattern.fullmatch(clean)
            if m:
                # Group 1 (double quote) atau Group 2 (single quote)
                val = (m.group(1) or m.group(2) or "").strip()
                if not val:
                    break
                compiled_rules.append({"type": rule_type, "val": val, "raw": clean})
                matched = True
                break

        if not matched:
            unparseable_rules.append(clean)

    return compiled_rules, unparseable_rules

def parse_markdown_test_case_content(content: str) -> Dict[str, Any]:
    """Menguraikan konten teks Markdown kasus uji sesuai kontrak standar di docs/test-case-contract.md."""
    parsed: Dict[str, Any] = {
        "id": "UNKNOWN",
        "title": "Unknown Test Case",
        "type": "Positive",
        "execution_mode": "deterministic",
        "approval_status": "pending",
        "approval_hash": None,
        "target_url": "",
        "account": "",
        "preconditions": [],
        "test_data": {},
        "steps": [],
        "expected_results": [],
        "raw_content": content
    }

    # 1. Parse Metadata Header
    for line in content.splitlines():
        line_s = line.strip()
        if line_s.startswith("# "):
            parts = line_s.strip("# ").split(":", 1)
            if len(parts) == 2:
                parsed["id"] = parts[0].strip()
                parsed["title"] = parts[1].strip()
        elif "**ID**:" in line_s:
            parsed["id"] = line_s.split("**ID**:", 1)[1].strip()
        elif "**Title**:" in line_s or "**Judul**:" in line_s:
            parsed["title"] = line_s.split(":", 1)[1].strip().strip("* ")
        elif "**Type**:" in line_s or "**Tipe**:" in line_s:
            parsed["type"] = line_s.split(":", 1)[1].strip().strip("* ")
        elif "**Execution Mode**:" in line_s:
            parsed["execution_mode"] = line_s.split(":", 1)[1].strip().strip("* ").split()[0].lower()
        elif "**Approval Status**:" in line_s:
            parsed["approval_status"] = line_s.split(":", 1)[1].strip().strip("* ").split()[0].lower()
        elif "**Approval Hash**:" in line_s:
            parsed["approval_hash"] = line_s.split(":", 1)[1].strip().strip("* ").split()[0].lower()
        elif "**Target URL**:" in line_s:
            parsed["target_url"] = line_s.split(":", 1)[1].strip().strip("* ")
        elif "**Account**:" in line_s or "**Akun Uji**:" in line_s:
            parsed["account"] = line_s.split(":", 1)[1].strip().strip("* ")

    # 2. Parse Structured Sections
    current_sec = None
    for line in content.splitlines():
        line_s = line.strip()
        if not line_s:
            continue

        if "|" not in line_s:
            clean_header = re.sub(r'^(?:#{1,6}|h[1-6]\.|\*{1,2})\s*|\s*(?:\*{1,2}|:)$', '', line_s).strip().lower()
            if clean_header in ["preconditions", "precondition", "pra-kondisi", "prakondisi"]:
                current_sec = "preconditions"
                continue
            elif clean_header in ["test data", "data uji"]:
                current_sec = "test_data"
                continue
            elif clean_header in ["test steps", "test step", "steps", "langkah", "langkah pengujian"]:
                current_sec = "steps"
                continue
            elif clean_header in ["expected results", "expected result", "hasil yang diharapkan", "hasil"]:
                current_sec = "expected_results"
                continue

        if not current_sec:
            continue

        if current_sec == "preconditions":
            item = re.sub(r'^[-*•]\s*|^\d+[\.\)]\s*', '', line_s).strip()
            if item:
                parsed["preconditions"].append(item)
        elif current_sec == "test_data":
            clean_l = re.sub(r'^[-*•]\s*|^\d+[\.\)]\s*', '', line_s).strip()
            if ":" in clean_l:
                k, v = clean_l.split(":", 1)
                parsed["test_data"][k.strip()] = v.strip()
        elif current_sec == "expected_results":
            item = re.sub(r'^[-*•]\s*|^\d+[\.\)]\s*', '', line_s).strip()
            if item:
                parsed["expected_results"].append(item)
        elif current_sec == "steps" and "|" in line_s:
            norm_line = line_s.replace("||", "|")
            cols = [c.strip() for c in norm_line.split("|")[1:-1]]
            if len(cols) >= 4 and cols[0].lower() not in ["step", ":---", "---"]:
                step_num = cols[0]
                action = cols[1].lower()
                target = cols[2]
                val = cols[3] if len(cols) > 3 else "-"
                outcome = cols[4] if len(cols) > 4 else ""

                val_clean = re.sub(r'^[•\s-]+$', '-', val).strip()
                if not val_clean:
                    val_clean = "-"

                parsed["steps"].append({
                    "step_number": step_num,
                    "action": action,
                    "target": target,
                    "value": val_clean,
                    "expected_step_outcome": outcome
                })

    return parsed

def parse_markdown_test_case(tc_path: Path) -> Dict[str, Any]:
    """Menguraikan file Markdown kasus uji dari berkas lokal."""
    if not tc_path.exists():
        raise FileNotFoundError(f"File kasus uji tidak ditemukan: {tc_path}")

    content = tc_path.read_text(encoding="utf-8")
    return parse_markdown_test_case_content(content)


def validate_test_case_contract(tc: Dict[str, Any]) -> List[str]:
    """Memvalidasi integritas kasus uji terhadap kontrak baku dengan aturan fail-closed."""
    errors = []
    if not tc.get("id") or tc.get("id") == "UNKNOWN":
        errors.append("Field 'ID' wajib diisi.")
    if not tc.get("title") or tc.get("title") == "Unknown Test Case":
        errors.append("Field 'Title' wajib diisi.")

    # 1. Fail-closed on unsupported execution mode
    mode = tc.get("execution_mode", "deterministic").lower()
    if mode != "deterministic":
        errors.append(f"Mode eksekusi '{mode}' belum didukung pada rilis ini. Gunakan 'deterministic'.")

    # 2. Steps validation
    steps = tc.get("steps", [])
    if not steps:
        errors.append("Tabel 'Test Steps' kosong atau format kolom tidak sesuai.")
    else:
        valid_actions = {"navigate", "fill", "click", "select", "wait", "assert"}
        for idx, s in enumerate(steps):
            expected_step_num = str(idx + 1)
            actual_step_num = str(s.get("step_number", "")).strip()
            if actual_step_num != expected_step_num:
                errors.append(f"Nomor langkah tidak berurutan: diharapkan '{expected_step_num}', ditemukan '{actual_step_num}'.")

            act = s.get("action", "").lower()
            if act not in valid_actions:
                errors.append(f"Aksi '{act}' pada langkah {actual_step_num} tidak didukung. Pilihan valid: {sorted(list(valid_actions))}")

    # 3. Expected Results validation & compilation
    raw_expectations = tc.get("expected_results", [])
    if not raw_expectations:
        errors.append("Bagian 'Expected Results' wajib mendefinisikan minimal satu kriteria hasil.")
    else:
        _, unparseable = compile_expected_results(raw_expectations)
        if unparseable:
            errors.append(
                f"Kriteria hasil tidak dapat dikompilasi ke asersi mesin: {unparseable}. "
                "Gunakan format baku seperti: url contains \"...\", text contains \"...\", element \"...\" is visible."
            )

    return errors
