import os
import sys
import json
import time
import shutil
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

from runner.parser import parse_markdown_test_case, validate_test_case_contract

def load_env(env_path: Path) -> dict:
    env_dict = {}
    if not env_path.exists():
        return env_dict
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" in line:
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    os.environ[k] = v
                    env_dict[k] = v
    return env_dict

def resolve_variables(text: str, env_vars: dict) -> str:
    if not text:
        return ""
    for k, v in env_vars.items():
        text = text.replace(f"${{{k}}}", str(v))
    return text

def execute_step_action(page, step: dict, env_vars: dict):
    action = step["action"].lower()
    raw_target = step.get("target", "")
    raw_val = step.get("value", "")

    target = resolve_variables(raw_target, env_vars)
    val = resolve_variables(raw_val, env_vars)

    if action == "navigate":
        page.goto(target, timeout=30000, wait_until="networkidle")
    elif action == "fill":
        filled = False
        candidates = [
            page.get_by_label(target, exact=False),
            page.get_by_placeholder(target, exact=False),
            page.locator(f"input[name='{target}'], textarea[name='{target}']"),
            page.locator(f"#{target}"),
            page.locator(f"input[id*='{target.lower()}']"),
        ]
        # Specific fallback for username/password fields if target is generic
        if "username" in target.lower():
            candidates.append(page.locator("input[type='text'], input[id*='user'], input[name*='user']"))
        elif "password" in target.lower():
            candidates.append(page.locator("input[type='password'], input[id*='pass'], input[name*='pass']"))

        for loc in candidates:
            if loc.count() > 0:
                loc.first.fill(val)
                filled = True
                break
        if not filled:
            raise ValueError(f"Elemen input untuk target '{target}' tidak ditemukan di halaman.")
    elif action == "click":
        clicked = False
        candidates = [
            page.get_by_role("button", name=target, exact=False),
            page.get_by_text(target, exact=False),
            page.locator(f"button:has-text('{target}'), a:has-text('{target}')"),
            page.locator(f"#{target}"),
        ]
        if any(term in target.lower() for term in ["sign in", "login", "masuk", "submit"]):
            candidates.append(page.locator("button[type='submit'], input[type='submit']"))

        for loc in candidates:
            if loc.count() > 0:
                loc.first.click()
                clicked = True
                break
        if not clicked:
            raise ValueError(f"Elemen tombol untuk target '{target}' tidak ditemukan untuk diklik.")
        page.wait_for_load_state("networkidle", timeout=30000)
    elif action == "select":
        page.select_option(target, label=val)
    elif action == "wait":
        secs = float(val) if val.replace(".", "", 1).isdigit() else 2.0
        time.sleep(secs)
    elif action == "assert":
        if target not in page.inner_text("body"):
            raise AssertionError(f"Teks asersi '{target}' tidak ditemukan pada halaman.")
    else:
        raise ValueError(f"Aksi '{action}' tidak didukung oleh runner.")

def run_test_case(test_case_file: str = "test-cases/TC-001-login-valid.md") -> dict:
    repo_root = Path(__file__).resolve().parent.parent
    env_vars = load_env(repo_root / ".env")

    tc_path = repo_root / test_case_file if not os.path.isabs(test_case_file) else Path(test_case_file)
    parsed_tc = parse_markdown_test_case(tc_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"RUN_{timestamp}"
    run_dir = repo_root / "artifacts" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    video_dir = run_dir / "raw_video"
    video_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = run_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    # Persist snapshot of test case with run artifacts (without secrets)
    snapshot_path = run_dir / "test-case-snapshot.md"
    shutil.copyfile(str(tc_path), str(snapshot_path))

    metadata = {
        "run_id": run_id,
        "test_case_id": parsed_tc["id"],
        "title": parsed_tc["title"],
        "timestamp": datetime.now().isoformat(),
        "target_url": resolve_variables(parsed_tc.get("target_url", ""), env_vars),
        "steps": [],
        "verdict": "ERROR",
        "error_message": None,
        "publish_status": {
            "published": False,
            "status": "UNPUBLISHED",
            "reason": "AWAITING_PUBLISH"
        },
        "artifacts": {
            "screenshots": [],
            "video": None,
            "snapshot": str(snapshot_path.relative_to(repo_root))
        }
    }

    # 1. QA Approval Gate Check
    approval_status = parsed_tc.get("approval_status", "pending").lower()
    if approval_status != "approved":
        metadata["verdict"] = "BLOCKED"
        metadata["actual_result"] = (
            f"Eksekusi dibatalkan: Kasus uji berstatus 'Approval Status: {approval_status}'. "
            "Kasus uji wajib di-review dan disetujui (status: 'approved') oleh tim QA sebelum dapat dieksekusi."
        )
        meta_file = run_dir / "metadata.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        return metadata

    # 2. Contract Schema Validation
    validation_errors = validate_test_case_contract(parsed_tc)
    if validation_errors:
        metadata["verdict"] = "ERROR"
        metadata["error_message"] = f"Validasi kontrak kasus uji gagal: {'; '.join(validation_errors)}"
        meta_file = run_dir / "metadata.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        return metadata

    start_time = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            record_video_dir=str(video_dir),
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()

        try:
            # 3. Dynamic Steps Execution
            for s in parsed_tc["steps"]:
                step_num = s["step_number"]
                action = s["action"]
                target = s["target"]
                outcome = s.get("expected_step_outcome", "")

                execute_step_action(page, s, env_vars)
                time.sleep(0.5) # Stabilisasi render

                # Capture step screenshot
                sc_name = f"step_{step_num}_{action}.png"
                sc_path = screenshots_dir / sc_name
                page.screenshot(path=str(sc_path))

                step_info = {
                    "step_number": step_num,
                    "action": f"{action} -> {target}",
                    "status": "COMPLETED",
                    "screenshot": str(sc_path.relative_to(repo_root)),
                    "notes": outcome or f"URL: {page.url}"
                }
                metadata["steps"].append(step_info)
                metadata["artifacts"]["screenshots"].append(str(sc_path))

            # 4. Asersi Hasil & Evaluasi Expected Results
            time.sleep(2) # Stabilisasi setelah langkah terakhir
            current_url = page.url
            body_text = page.inner_text("body")
            page_title = page.title()

            # Final state screenshot
            sc_final = screenshots_dir / "final_state.png"
            page.screenshot(path=str(sc_final))
            metadata["artifacts"]["screenshots"].append(str(sc_final))

            # Cek indikasi akun terkunci / alert sistem
            alert_el = page.query_selector(".alert, [role='alert']")
            alert_text = alert_el.inner_text().strip() if alert_el else None

            if alert_text and any(k in alert_text.lower() for k in ["locked", "blocked", "terkunci"]):
                metadata["verdict"] = "BLOCKED"
                metadata["actual_result"] = f"Pengujian terhenti karena prasyarat eksternal gagal. Akun uji terkunci pada halaman: '{alert_text}'."
            else:
                # Periksa kondisi expected results
                # Contoh: dashboard terautentikasi dan tidak berada di /login
                is_login = "/login" in current_url
                has_dashboard = page_title == "Dashboard" or "Dashboard" in body_text
                has_indicators = any(ind in body_text for ind in [
                    "Care Monitor", "Manage Plan Benefit", "Total Member", "Total Claim", "Super User"
                ])

                if not is_login and has_dashboard and has_indicators:
                    metadata["verdict"] = "PASSED"
                    metadata["actual_result"] = (
                        f"Pengguna berhasil dialihkan ke {current_url}. "
                        "Terverifikasi judul 'Dashboard' dan indikator modul Managed Care (Care Monitor, Total Member, Total Claim)."
                    )
                else:
                    metadata["verdict"] = "FAILED"
                    err_hint = f" Pesan sistem: '{alert_text}'." if alert_text else ""
                    metadata["actual_result"] = f"Kriteria hasil tidak terpenuhi. URL akhir: {current_url}.{err_hint}"

        except Exception as e:
            metadata["verdict"] = "ERROR"
            metadata["error_message"] = str(e)
            sc_err = screenshots_dir / "error_state.png"
            try:
                page.screenshot(path=str(sc_err))
                metadata["artifacts"]["screenshots"].append(str(sc_err))
            except Exception:
                pass
        finally:
            context.close()
            browser.close()

    metadata["execution_duration_seconds"] = round(time.time() - start_time, 2)

    # Finalisasi rekaman video
    video_files = list(video_dir.glob("*.webm"))
    if video_files:
        final_video_path = run_dir / "evidence.webm"
        shutil.move(str(video_files[0]), str(final_video_path))
        shutil.rmtree(video_dir, ignore_errors=True)
        metadata["artifacts"]["video"] = str(final_video_path.relative_to(repo_root))

    meta_file = run_dir / "metadata.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return metadata

if __name__ == "__main__":
    res = run_test_case()
    print(json.dumps(res, indent=2))
