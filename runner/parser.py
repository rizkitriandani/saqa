from pathlib import Path
from typing import Dict, Any, List

def parse_markdown_test_case(tc_path: Path) -> Dict[str, Any]:
    """Menguraikan file Markdown kasus uji sesuai kontrak standar di docs/test-case-contract.md."""
    if not tc_path.exists():
        raise FileNotFoundError(f"File kasus uji tidak ditemukan: {tc_path}")

    content = tc_path.read_text(encoding="utf-8")
    parsed: Dict[str, Any] = {
        "id": "UNKNOWN",
        "title": "Unknown Test Case",
        "type": "Positive",
        "execution_mode": "deterministic",
        "approval_status": "pending",
        "target_url": "",
        "account": "",
        "preconditions": [],
        "test_data": {},
        "steps": [],
        "expected_results": []
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
        elif "**Target URL**:" in line_s:
            parsed["target_url"] = line_s.split(":", 1)[1].strip().strip("* ")
        elif "**Account**:" in line_s or "**Akun Uji**:" in line_s:
            parsed["account"] = line_s.split(":", 1)[1].strip().strip("* ")

    # 2. Parse Structured Sections
    current_sec = None
    for line in content.splitlines():
        line_s = line.strip()
        if line_s.startswith("## "):
            sec_name = line_s.strip("# ").lower()
            if "precondition" in sec_name:
                current_sec = "preconditions"
            elif "test data" in sec_name or "data uji" in sec_name:
                current_sec = "test_data"
            elif "step" in sec_name or "langkah" in sec_name:
                current_sec = "steps"
            elif "expected result" in sec_name or "hasil yang diharapkan" in sec_name:
                current_sec = "expected_results"
            else:
                current_sec = None
            continue

        if not current_sec or not line_s:
            continue

        if current_sec == "preconditions" and line_s.startswith("-"):
            parsed["preconditions"].append(line_s.strip("- *"))
        elif current_sec == "test_data" and (line_s.startswith("-") or ":" in line_s):
            clean_l = line_s.strip("- *")
            if ":" in clean_l:
                k, v = clean_l.split(":", 1)
                parsed["test_data"][k.strip()] = v.strip()
        elif current_sec == "expected_results" and line_s.startswith("-"):
            parsed["expected_results"].append(line_s.strip("- *"))
        elif current_sec == "steps" and "|" in line_s:
            cols = [c.strip() for c in line_s.split("|")[1:-1]]
            if len(cols) >= 4 and cols[0].lower() not in ["step", ":---", "---"]:
                step_num = cols[0]
                action = cols[1].lower()
                target = cols[2]
                val = cols[3] if len(cols) > 3 else "-"
                outcome = cols[4] if len(cols) > 4 else ""
                parsed["steps"].append({
                    "step_number": step_num,
                    "action": action,
                    "target": target,
                    "value": val,
                    "expected_step_outcome": outcome
                })

    return parsed

def validate_test_case_contract(tc: Dict[str, Any]) -> List[str]:
    """Memvalidasi integritas kasus uji terhadap kontrak baku."""
    errors = []
    if not tc.get("id") or tc.get("id") == "UNKNOWN":
        errors.append("Field 'ID' wajib diisi.")
    if not tc.get("title") or tc.get("title") == "Unknown Test Case":
        errors.append("Field 'Title' wajib diisi.")
    if not tc.get("steps"):
        errors.append("Tabel 'Test Steps' kosong atau format kolom tidak sesuai.")
    if not tc.get("expected_results"):
        errors.append("Bagian 'Expected Results' wajib mendefinisikan minimal satu kriteria hasil.")
    
    valid_actions = {"navigate", "fill", "click", "select", "wait", "assert"}
    for s in tc.get("steps", []):
        act = s.get("action", "").lower()
        if act not in valid_actions:
            errors.append(f"Aksi '{act}' pada langkah {s.get('step_number')} tidak didukung. Pilihan valid: {sorted(list(valid_actions))}")

    return errors
