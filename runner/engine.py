import os
import sys
import json
import time
import shutil
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

def load_env(env_path: Path):
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k not in os.environ:
                os.environ[k] = v

def run_test_case(test_case_file: str = "test-cases/TC-001-login-valid.md") -> dict:
    repo_root = Path(__file__).resolve().parent.parent
    load_env(repo_root / ".env")

    dev_base_url = os.getenv("DEV_BASE_URL", "https://dev-bcalife.izihealth.co.id/")
    username = os.getenv("QA_USERNAME", "")
    password = os.getenv("QA_PASSWORD", "")

    if not username or not password:
        raise ValueError("QA_USERNAME or QA_PASSWORD not set in environment or .env file")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"RUN_{timestamp}"
    run_dir = repo_root / "artifacts" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    video_dir = run_dir / "raw_video"
    video_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = run_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    # Load test case info from markdown if available
    tc_path = repo_root / test_case_file if not os.path.isabs(test_case_file) else Path(test_case_file)
    tc_id = "TC-001"
    tc_title = "Login dengan username & password yang valid"
    if tc_path.exists():
        with open(tc_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("# "):
                    parts = line.strip("# \n").split(":", 1)
                    if len(parts) == 2:
                        tc_id = parts[0].strip()
                        tc_title = parts[1].strip()
                elif "**ID**:" in line:
                    tc_id = line.split("**ID**:", 1)[1].strip()
                elif "**Judul**:" in line:
                    tc_title = line.split("**Judul**:", 1)[1].strip()

    metadata = {
        "run_id": run_id,
        "test_case_id": tc_id,
        "title": tc_title,
        "timestamp": datetime.now().isoformat(),
        "target_url": dev_base_url,
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
            "video": None
        }
    }

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
            # Step 1: Navigasi ke halaman login
            page.goto(dev_base_url, timeout=30000, wait_until="networkidle")
            sc1_path = screenshots_dir / "01_halaman_login.png"
            page.screenshot(path=str(sc1_path))
            metadata["steps"].append({
                "step_number": 1,
                "action": "Akses halaman login target",
                "status": "COMPLETED",
                "screenshot": str(sc1_path.relative_to(repo_root)),
                "notes": f"URL: {page.url}, Judul: {page.title()}"
            })
            metadata["artifacts"]["screenshots"].append(str(sc1_path))

            # Step 2: Input username & password
            page.fill("#username", username)
            page.fill("#password-input", password)
            sc2_path = screenshots_dir / "02_kredensial_diisi.png"
            page.screenshot(path=str(sc2_path))
            metadata["steps"].append({
                "step_number": 2,
                "action": "Input username & password pada formulir",
                "status": "COMPLETED",
                "screenshot": str(sc2_path.relative_to(repo_root)),
                "notes": "Kredensial diisi (kolom password terlindungi)"
            })
            metadata["artifacts"]["screenshots"].append(str(sc2_path))

            # Step 3: Klik tombol Sign In
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle", timeout=30000)

            # Tunggu transisi URL atau elemen dashboard
            time.sleep(2) # Stabilisasi render SPA/DOM
            current_url = page.url
            body_text = page.inner_text("body")
            page_title = page.title()

            sc3_path = screenshots_dir / "03_halaman_dashboard.png"
            page.screenshot(path=str(sc3_path))
            metadata["steps"].append({
                "step_number": 3,
                "action": "Klik tombol Sign In dan tunggu pengalihan",
                "status": "COMPLETED",
                "screenshot": str(sc3_path.relative_to(repo_root)),
                "notes": f"URL akhir: {current_url}, Judul: {page_title}"
            })
            metadata["artifacts"]["screenshots"].append(str(sc3_path))

            # Step 4: Asersi Keberhasilan Login
            is_login_page = "/login" in current_url
            has_managed_care = "Managed Care" in body_text or "managed-care" in current_url.lower() or "Managed Care" in page_title

            alert_el = page.query_selector(".alert, [role='alert']")
            alert_text = alert_el.inner_text().strip() if alert_el else None

            if not is_login_page and has_managed_care:
                metadata["verdict"] = "PASSED"
                metadata["actual_result"] = f"Pengguna berhasil login dan dialihkan ke {current_url}. Terverifikasi indikator Managed Care."
            elif alert_text and ("locked" in alert_text.lower() or "blocked" in alert_text.lower() or "terkunci" in alert_text.lower()):
                metadata["verdict"] = "BLOCKED"
                metadata["actual_result"] = f"Pengujian terhenti karena prasyarat eksternal gagal. Akun uji terkunci pada halaman login: '{alert_text}'."
            else:
                metadata["verdict"] = "FAILED"
                detail = f" Pesan sistem pada halaman: '{alert_text}'." if alert_text else ""
                metadata["actual_result"] = f"Pengguna gagal masuk dan tetap berada pada URL: {current_url}. Indikator Managed Care tidak ditemukan.{detail}"

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
