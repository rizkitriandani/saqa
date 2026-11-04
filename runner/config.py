import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

SUPPORTED_CONFIG_VERSION = 1
SUPPORTED_INPUT_TRIGGERS = {"cli", "jira_webhook"}
SUPPORTED_INPUT_SOURCES = {"repo", "cli", "jira_issue"}
SUPPORTED_OUTPUT_TYPES = {"local", "google_drive", "jira_comment"}
SUPPORTED_RUNNER_TARGETS = {"local", "github", "gitlab"}

def load_project_env(project_root: Path) -> Dict[str, str]:
    """
    Membaca variabel lingkungan dari .env proyek ke dictionary terisolasi.
    Tidak melakukan mutasi global pada os.environ agar Proyek A tidak mencemari Proyek B.
    Prioritas: Nilai dari os.environ sistem tetap dihormati jika sudah ada.
    """
    env_vars: Dict[str, str] = {}
    env_file = project_root / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                env_vars[k] = v

    # Variabel sistem yang sudah diset memiliki prioritas
    for k in list(env_vars.keys()):
        if k in os.environ:
            env_vars[k] = os.environ[k]

    return env_vars

def validate_project_config(cfg: Dict[str, Any]) -> List[str]:
    """Memvalidasi integritas dan keamanan konfigurasi saqa.json."""
    errors = []

    if cfg.get("version") != SUPPORTED_CONFIG_VERSION:
        errors.append(f"Versi konfigurasi tidak didukung: {cfg.get('version')}. Diharapkan: {SUPPORTED_CONFIG_VERSION}.")

    if not cfg.get("project_id"):
        errors.append("Field 'project_id' wajib diisi.")

    env_cfg = cfg.get("environment", {})
    base_url = env_cfg.get("base_url", "")
    if not base_url:
        errors.append("Field 'environment.base_url' wajib diisi.")
    else:
        p = urlparse(base_url)
        if not p.scheme or not p.netloc:
            errors.append(f"URL 'environment.base_url' ({base_url}) tidak valid.")

    input_cfg = cfg.get("input", {})
    trigger = input_cfg.get("trigger", "cli")
    if trigger not in SUPPORTED_INPUT_TRIGGERS:
        errors.append(
            f"Pemicu input '{trigger}' belum didukung pada rilis ini. "
            f"Pilihan aktif: {sorted(list(SUPPORTED_INPUT_TRIGGERS))}."
        )

    src = input_cfg.get("source", "repo")
    if src not in SUPPORTED_INPUT_SOURCES:
        errors.append(
            f"Sumber input '{src}' belum didukung pada rilis ini. "
            f"Pilihan aktif: {sorted(list(SUPPORTED_INPUT_SOURCES))}."
        )
    elif src == "jira_issue":
        statuses = input_cfg.get("trigger_statuses", [])
        if statuses and not isinstance(statuses, list):
            errors.append("Field 'input.trigger_statuses' wajib berupa list nama status string.")

    runner_target = cfg.get("runner_target", "local")
    if runner_target not in SUPPORTED_RUNNER_TARGETS:
        errors.append(
            f"Target runner '{runner_target}' tidak didukung. "
            f"Pilihan valid: {sorted(list(SUPPORTED_RUNNER_TARGETS))}."
        )

    outputs = cfg.get("outputs", [])
    if not outputs:
        errors.append("Minimal satu output wajib dikonfigurasi pada list 'outputs'.")
    for idx, out in enumerate(outputs):
        otype = out.get("type", "")
        if otype not in SUPPORTED_OUTPUT_TYPES:
            errors.append(
                f"Tipe output '{otype}' pada indeks {idx} belum didukung. "
                f"Pilihan aktif: {sorted(list(SUPPORTED_OUTPUT_TYPES))}."
            )

    return errors

def load_project_config(project_root: Path) -> Dict[str, Any]:
    """
    Memuat konfigurasi saqa.json dari root proyek aktif.
    Jika tidak ditemukan, membuat konfigurasi fallback default berbasis .env lokal.
    """
    cfg_file = project_root / "saqa.json"
    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            raise ValueError(f"Berkas saqa.json pada {project_root} rusak atau bukan JSON valid: {str(e)}")

        errors = validate_project_config(cfg)
        if errors:
            raise ValueError(f"Validasi saqa.json gagal: {'; '.join(errors)}")
        return cfg

    # Fallback konfigurasi default jika saqa.json belum dibuat (Hanya lokal, tidak otomatis upload)
    env_vars = load_project_env(project_root)
    base_url = env_vars.get("DEV_BASE_URL", "")
    p = urlparse(base_url) if base_url else None
    origin = f"{p.scheme}://{p.netloc}" if p and p.scheme and p.netloc else ""

    return {
        "version": SUPPORTED_CONFIG_VERSION,
        "project_id": project_root.name,
        "environment": {
            "base_url": base_url,
            "allowed_origins": [origin] if origin else [],
            "username_env": "QA_USERNAME",
            "password_env": "QA_PASSWORD"
        },
        "input": {
            "trigger": "cli",
            "source": "repo",
            "test_cases_dir": "test-cases"
        },
        "outputs": [
            {"type": "local"}
        ]
    }

def create_project_config(
    project_root: Path,
    project_id: str,
    base_url: str,
    enable_google_drive: bool = False,
    overwrite: bool = False
) -> Path:
    """
    Membuat berkas saqa.json non-rahasia dan template .env.example di root proyek aktif.
    """
    cfg_file = project_root / "saqa.json"
    if cfg_file.exists() and not overwrite:
        raise FileExistsError(f"Konfigurasi saqa.json sudah ada di {project_root}. Gunakan overwrite=True jika ingin menimpa.")

    p = urlparse(base_url)
    origin = f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else base_url

    outputs = [{"type": "local"}]
    if enable_google_drive:
        outputs.append({
            "type": "google_drive",
            "folder_id_env": "GOOGLE_DRIVE_FOLDER_ID",
            "credentials_env": "GOOGLE_APPLICATION_CREDENTIALS"
        })

    config_data = {
        "version": SUPPORTED_CONFIG_VERSION,
        "project_id": project_id,
        "environment": {
            "base_url": base_url,
            "allowed_origins": [origin],
            "username_env": "QA_USERNAME",
            "password_env": "QA_PASSWORD"
        },
        "input": {
            "trigger": "cli",
            "source": "repo",
            "test_cases_dir": "test-cases"
        },
        "outputs": outputs
    }

    errors = validate_project_config(config_data)
    if errors:
        raise ValueError(f"Gagal membuat konfigurasi: {'; '.join(errors)}")

    cfg_file.write_text(json.dumps(config_data, indent=2) + "\n", encoding="utf-8")

    # Generate template .env.example non-rahasia hanya jika belum ada atau overwrite=True
    example_env = project_root / ".env.example"
    if not example_env.exists() or overwrite:
        env_lines = [
            f"# SAQA Configuration for project: {project_id}",
            f"DEV_BASE_URL={base_url}",
            "QA_USERNAME=your_username_here",
            "QA_PASSWORD=your_password_here"
        ]
        if enable_google_drive:
            env_lines.extend([
                "GOOGLE_DRIVE_FOLDER_ID=your_shared_drive_folder_id_here",
                "GOOGLE_APPLICATION_CREDENTIALS=credentials/service-account.json"
            ])
        example_env.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    return cfg_file
