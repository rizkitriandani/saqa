import os
import re
import sys
import json
import time
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

from urllib.parse import urlparse
from runner.parser import (
    parse_markdown_test_case,
    validate_test_case_contract,
    compute_canonical_content_hash,
    compile_expected_results,
    ALLOWED_ENV_VARS
)

def get_allowed_origins(dev_base_url: str) -> set:
    """Mengembalikan daftar origin tepercaya yang diizinkan untuk navigasi browser."""
    origins = {"http://localhost", "http://127.0.0.1", "file://"}
    if dev_base_url:
        p = urlparse(dev_base_url)
        if p.scheme and p.netloc:
            origins.add(f"{p.scheme}://{p.netloc}")
    extra = os.environ.get("ALLOWED_ORIGINS", "")
    if extra:
        for o in extra.split(","):
            if o.strip():
                origins.add(o.strip())
    return origins

def validate_navigation_origin(url_str: str, allowed_origins: set):
    """Memeriksa apakah URL yang dituju berada dalam allowlist origin tepercaya."""
    if url_str.startswith("file://"):
        return
    p = urlparse(url_str)
    if not p.scheme or not p.netloc:
        raise ValueError(f"URL navigasi '{url_str}' tidak valid (membutuhkan scheme dan domain).")
    origin = f"{p.scheme}://{p.netloc}"
    if origin not in allowed_origins:
        raise PermissionError(
            f"Navigasi ke origin '{origin}' diblokir oleh kebijakan keamanan. "
            f"Origin yang diizinkan: {sorted(list(allowed_origins))}"
        )

def load_env(env_path: Path) -> dict:
    env_dict = {}
    if not env_path.exists():
        return env_dict
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            # Hanya isi jika belum ada di environment sistem
            if k not in os.environ:
                os.environ[k] = v
            env_dict[k] = os.environ[k]
    return env_dict

def resolve_variables(text: str, env_vars: dict, allow_password: bool = False) -> str:
    """
    Menyubstitusi variabel dari allowlist ke dalam teks.
    Kebijakan Keamanan:
    - Variabel di luar ALLOWED_ENV_VARS langsung ditolak.
    - QA_PASSWORD hanya diizinkan untuk aksi input (allow_password=True).
    - Variabel yang belum terdefinisi / kosong ditolak (tidak boleh disubstitusi jadi string kosong).
    """
    if not text:
        return ""
    matches = re.findall(r'\$\{([^}]+)\}', text)
    for var_name in matches:
        if var_name not in ALLOWED_ENV_VARS:
            raise ValueError(
                f"Variabel '${{{var_name}}}' tidak diizinkan. "
                f"Hanya variabel terdaftar yang boleh digunakan: {sorted(list(ALLOWED_ENV_VARS))}"
            )
        if var_name == "QA_PASSWORD" and not allow_password:
            raise PermissionError(
                "Variabel '${QA_PASSWORD}' dilarang digunakan di luar kolom input formulir/fill "
                "(mencegah kebocoran kata sandi pada URL, parameter GET, atau teks terbuka)."
            )
        val = env_vars.get(var_name, os.environ.get(var_name, ""))
        if not val:
            raise ValueError(
                f"Variabel '${{{var_name}}}' belum disetel di environment atau .env. Nilai tidak boleh kosong."
            )
        text = text.replace(f"${{{var_name}}}", str(val))
    return text

def find_unique_element(page, candidates: list, target_desc: str):
    """
    Mencari elemen interaktif dengan verifikasi keunikan (menolak penargetan ambigu).
    Hanya mengembalikan elemen jika target secara spesifik menemukan tepat 1 elemen aktif.
    """
    matching_locators = []
    for loc in candidates:
        try:
            cnt = loc.count()
        except Exception:
            continue

        if cnt == 1:
            matching_locators.append(loc)
        elif cnt > 1:
            vis = [loc.nth(i) for i in range(cnt) if loc.nth(i).is_visible()]
            if len(vis) == 1:
                matching_locators.append(vis[0])
            elif len(vis) > 1:
                raise ValueError(
                    f"Penargetan ambigu: ditemukan {len(vis)} elemen aktif untuk target '{target_desc}'. "
                    "Gunakan selector ID unik atau label spesifik."
                )

    if not matching_locators:
        return None
    return matching_locators[0]

def execute_step_action(page, step: dict, env_vars: dict, allowed_origins: set):
    action = step["action"].lower()
    raw_target = step.get("target", "")
    raw_val = step.get("value", "")

    # Keamanan: QA_PASSWORD hanya diizinkan untuk value pada aksi fill
    target = resolve_variables(raw_target, env_vars, allow_password=False)
    val = resolve_variables(raw_val, env_vars, allow_password=(action == "fill"))

    if action == "navigate":
        validate_navigation_origin(target, allowed_origins)
        page.goto(target, timeout=30000, wait_until="networkidle")
    elif action == "fill":
        candidates = [
            page.get_by_label(target, exact=True),
            page.get_by_label(target, exact=False),
            page.get_by_placeholder(target, exact=True),
            page.get_by_placeholder(target, exact=False),
            page.locator(f"#{target}"),
            page.locator(f"input[name='{target}'], textarea[name='{target}']"),
        ]
        # Jika target diawali selector CSS/XPath
        if any(target.startswith(prefix) for prefix in ["#", ".", "[", "//"]):
            candidates.insert(0, page.locator(target))

        el = find_unique_element(page, candidates, target)
        if not el:
            raise ValueError(f"Elemen input untuk target '{target}' tidak ditemukan di halaman.")
        el.fill(val)

    elif action == "click":
        candidates = [
            page.get_by_role("button", name=target, exact=True),
            page.get_by_role("button", name=target, exact=False),
            page.locator(f"#{target}"),
            page.locator(f"button:has-text('{target}'), a:has-text('{target}')"),
        ]
        if any(target.startswith(prefix) for prefix in ["#", ".", "[", "//"]):
            candidates.insert(0, page.locator(target))

        el = find_unique_element(page, candidates, target)
        if not el:
            raise ValueError(f"Elemen tombol/interaktif untuk target '{target}' tidak ditemukan untuk diklik.")
        el.click()
        page.wait_for_load_state("networkidle", timeout=30000)

    elif action == "select":
        page.select_option(target, label=val)
    elif action == "wait":
        secs = float(val) if val.replace(".", "", 1).isdigit() else 2.0
        time.sleep(secs)
    elif action == "assert":
        if target not in page.inner_text("body"):
            raise AssertionError(f"Teks asersi langkah '{target}' tidak ditemukan pada halaman.")
    else:
        raise ValueError(f"Aksi '{action}' tidak didukung oleh runner.")

def preflight_validate(parsed_tc: dict, env_vars: dict, allowed_origins: set) -> list:
    """
    Validasi preflight menyeluruh sebelum browser diluncurkan:
    - Memastikan seluruh variabel yang digunakan terdaftar di ALLOWED_ENV_VARS dan bernilai tidak kosong.
    - Memastikan variabel QA_PASSWORD hanya digunakan pada aksi fill.
    - Memastikan seluruh URL target dan aksi navigasi berada pada allowlist origin tepercaya.
    - Memastikan seluruh kriteria Expected Results terkompilasi bersih tanpa aturan yang ambigu.
    """
    errors = []

    # 1. Target URL check
    raw_target_url = parsed_tc.get("target_url", "")
    if raw_target_url:
        try:
            resolved_url = resolve_variables(raw_target_url, env_vars, allow_password=False)
            validate_navigation_origin(resolved_url, allowed_origins)
        except Exception as e:
            errors.append(f"Target URL: {str(e)}")

    # 2. Steps validation
    for s in parsed_tc.get("steps", []):
        step_num = s.get("step_number")
        action = s.get("action", "").lower()
        raw_target = s.get("target", "")
        raw_val = s.get("value", "")

        try:
            target_res = resolve_variables(raw_target, env_vars, allow_password=False)
            if action == "navigate":
                validate_navigation_origin(target_res, allowed_origins)
        except Exception as e:
            errors.append(f"Langkah {step_num} Target: {str(e)}")

        try:
            resolve_variables(raw_val, env_vars, allow_password=(action == "fill"))
        except Exception as e:
            errors.append(f"Langkah {step_num} Value: {str(e)}")

    # 3. Expected results check
    _, unparseable = compile_expected_results(parsed_tc.get("expected_results", []))
    if unparseable:
        errors.append(f"Expected Results tidak terukur: {unparseable}")

    return errors

def run_test_case(test_case_file: str = "test-cases/TC-001-login-valid.md") -> dict:
    repo_root = Path(__file__).resolve().parent.parent
    env_vars = load_env(repo_root / ".env")

    tc_path = repo_root / test_case_file if not os.path.isabs(test_case_file) else Path(test_case_file)
    parsed_tc = parse_markdown_test_case(tc_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid_suffix = uuid.uuid4().hex[:8]
    run_id = f"RUN_{timestamp}_{uid_suffix}"
    run_dir = repo_root / "artifacts" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    video_dir = run_dir / "raw_video"
    video_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = run_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = run_dir / "test-case-snapshot.md"
    shutil.copyfile(str(tc_path), str(snapshot_path))

    target_url_resolved = ""
    try:
        target_url_resolved = resolve_variables(parsed_tc.get("target_url", ""), env_vars)
    except Exception:
        target_url_resolved = parsed_tc.get("target_url", "")

    metadata = {
        "run_id": run_id,
        "test_case_id": parsed_tc["id"],
        "title": parsed_tc["title"],
        "timestamp": datetime.now().isoformat(),
        "target_url": target_url_resolved,
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

    # 1. Approval Gate Check (Status + Hash Binding)
    approval_status = parsed_tc.get("approval_status", "pending").lower()
    approval_hash = parsed_tc.get("approval_hash")
    canonical_hash = compute_canonical_content_hash(parsed_tc.get("raw_content", ""))

    if approval_status != "approved":
        metadata["verdict"] = "BLOCKED"
        metadata["actual_result"] = (
            f"Eksekusi dibatalkan: Kasus uji berstatus 'Approval Status: {approval_status}'. "
            "Kasus uji wajib di-review dan disetujui (status: 'approved') oleh tim QA sebelum dapat dieksekusi."
        )
        with open(run_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        return metadata

    if not approval_hash or approval_hash != canonical_hash:
        metadata["verdict"] = "BLOCKED"
        metadata["actual_result"] = (
            "Eksekusi dibatalkan: Approval Hash tidak cocok atau kasus uji telah dimodifikasi setelah disetujui. "
            "Jalankan 'python3 cli.py approve <path>' untuk menyetujui ulang."
        )
        with open(run_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        return metadata

    # 2. Strict Contract Schema Validation (Fail-Closed)
    validation_errors = validate_test_case_contract(parsed_tc)
    if validation_errors:
        metadata["verdict"] = "ERROR"
        metadata["error_message"] = f"Validasi kontrak kasus uji gagal: {'; '.join(validation_errors)}"
        with open(run_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        return metadata

    dev_base_url = env_vars.get("DEV_BASE_URL", os.environ.get("DEV_BASE_URL", ""))
    allowed_origins = get_allowed_origins(dev_base_url)

    # 3. Preflight Check Sebelum Browser Diluncurkan
    preflight_errors = preflight_validate(parsed_tc, env_vars, allowed_origins)
    if preflight_errors:
        metadata["verdict"] = "ERROR"
        metadata["error_message"] = f"Validasi preflight gagal (browser tidak dibuka): {'; '.join(preflight_errors)}"
        with open(run_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        return metadata

    # Compile expected results
    compiled_assertions, _ = compile_expected_results(parsed_tc.get("expected_results", []))

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

                execute_step_action(page, s, env_vars, allowed_origins)
                time.sleep(0.5)

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

            # 4. Asersi Hasil Berdasarkan Aturan Terkompilasi
            time.sleep(2)
            current_url = page.url
            body_text = page.inner_text("body")
            headings_text = " ".join([
                h.inner_text().strip() for h in page.query_selector_all("h1, h2, h3, h4, h5, h6, [role='heading'], .page-title")
            ])

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
                # Evaluasi seluruh asersi generik
                failed_assertions = []
                for rule in compiled_assertions:
                    rtype = rule["type"]
                    val = rule["val"]
                    raw = rule["raw"]

                    if rtype == "url_not_contains":
                        if val in current_url:
                            failed_assertions.append(f"URL memuat '{val}' (aturan: '{raw}')")
                    elif rtype == "url_contains":
                        if val not in current_url:
                            failed_assertions.append(f"URL tidak memuat '{val}' (aturan: '{raw}')")
                    elif rtype == "url_equals":
                        if current_url != val:
                            failed_assertions.append(f"URL '{current_url}' != '{val}' (aturan: '{raw}')")
                    elif rtype == "heading_contains":
                        if val.lower() not in headings_text.lower():
                            failed_assertions.append(f"Heading tidak memuat '{val}' (aturan: '{raw}')")
                    elif rtype == "text_contains":
                        if val not in body_text:
                            failed_assertions.append(f"Teks '{val}' tidak ditemukan di halaman (aturan: '{raw}')")
                    elif rtype == "element_visible":
                        loc = page.locator(val)
                        cnt = loc.count()
                        if cnt == 0 or not any(loc.nth(i).is_visible() for i in range(cnt)):
                            failed_assertions.append(f"Elemen '{val}' tidak tampil (aturan: '{raw}')")

                if not failed_assertions:
                    metadata["verdict"] = "PASSED"
                    metadata["actual_result"] = (
                        f"Semua {len(compiled_assertions)} kriteria asersi berhasil divalidasi. "
                        f"URL akhir: {current_url}."
                    )
                else:
                    metadata["verdict"] = "FAILED"
                    metadata["actual_result"] = (
                        f"Kriteria hasil tidak terpenuhi ({len(failed_assertions)}/{len(compiled_assertions)} gagal): "
                        f"{'; '.join(failed_assertions)}. URL akhir: {current_url}."
                    )

        except AssertionError as ae:
            metadata["verdict"] = "FAILED"
            metadata["actual_result"] = f"Kegagalan asersi langkah: {str(ae)}"
            sc_err = screenshots_dir / "assertion_failure.png"
            try:
                page.screenshot(path=str(sc_err))
                metadata["artifacts"]["screenshots"].append(str(sc_err))
            except Exception:
                pass
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
