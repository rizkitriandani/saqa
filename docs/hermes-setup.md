# Panduan Integrasi: SAQA Plugin & Skill untuk Hermes Agent

*Tanggal: 2026-11-04*  
*Workspace: `/root/dev/sangQA`*  
*Spesifikasi: Nous Research Hermes Agent Plugin & Skill Specification*

Dokumen ini menjelaskan cara memasang dan mengaktifkan SAQA sebagai **Native Plugin** dan **Agent Skill** di dalam **Hermes Agent** (Nous Research).

---

## 1. Arsitektur Integrasi Hermes

Hermes Agent terhubung ke SAQA melalui dua antarmuka terstandarisasi:

```text
┌─────────────────────────────────────────────────────────────┐
│                 HERMES AGENT OPERATOR SHELL                 │
│      (CLI Terminal, Gateway: Telegram / Slack / Discord)    │
└──────────────────────────────┬──────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
┌───────────────────────────────┐   ┌───────────────────────────────┐
│ 1. Agent Skill (Pengetahuan)  │   │ 2. Native Plugin (Tool Calling)│
│    ~/.hermes/skills/saqa/     │   │    ~/.hermes/plugins/saqa/    │
│ • Panduan authoring kasus uji │   │ • saqa_run                    │
│ • Aturan audit logika & format│   │ • saqa_approve                │
│ • Dialog ramah bahasa alami   │   │ • saqa_diagnose               │
│                               │   │ • saqa_jira_inspect/process   │
│                               │   │ • Slash command: /saqa        │
└───────────────────────────────┘   └───────────────┬───────────────┘
                                                    │
                                                    ▼
                                    ┌───────────────────────────────┐
                                    │    SAQA Engine (Playwright)   │
                                    └───────────────────────────────┘
```

---

## 2. Langkah Instalasi Plugin & Skill ke Hermes

### Langkah 1: Pasang Symlink Skill & Plugin
Jalankan di terminal server tempat Hermes diinstal:

```bash
# 1. Pasang Skill
mkdir -p ~/.hermes/skills
ln -sfn /path/to/saqa/.agents/skills/saqa ~/.hermes/skills/saqa

# 2. Pasang Native Plugin
mkdir -p ~/.hermes/plugins
ln -sfn /path/to/saqa/plugins/hermes ~/.hermes/plugins/saqa
```

### Langkah 2: Setel Environment Variable di Hermes
Tambahkan path instalasi SAQA ke dalam berkas `~/.hermes/.env`:

```bash
SAQA_ROOT=/path/to/saqa
```

### Langkah 3: Aktifkan Plugin di Konfigurasi Hermes
Buka berkas `~/.hermes/config.yaml` dan pastikan plugin `saqa` diaktifkan:

```yaml
plugins:
  enabled:
    - saqa
```

---

## 3. Daftar Tools yang Disediakan untuk Model Hermes

Saat berinteraksi dengan Hermes, model AI dapat secara otomatis memanggil *structured tool calls* berikut:

| Tool Name | Parameter | Deskripsi |
| :--- | :--- | :--- |
| **`saqa_run`** | `test_case`, `no_publish`, `project_root` | Menjalankan kasus uji deterministik Playwright. |
| **`saqa_approve`** | `test_case`, `project_root` | Mengesahkan kasus uji dengan hash SHA-256. |
| **`saqa_diagnose`** | `run_id`, `attach_analysis`, `project_root` | Mengambil kegagalan screenshot/log atau menyematkan analisis AI. |
| **`saqa_jira_inspect`**| `issue_key`, `project_root` | Membaca tiket Jira Cloud secara read-only. |
| **`saqa_jira_process`**| `issue_key`, `no_publish`, `project_root` | Mengeksekusi pengujian dari tiket Jira dan mengunggah lampiran. |

---

## 4. Perintah Slash Command di Chat Hermes (`/saqa`)

Operator manusia di chat terminal Hermes maupun bot Telegram/Slack dapat mengetikkan perintah langsung:

```text
/saqa help
/saqa run test-cases/TC-001.md
/saqa approve test-cases/TC-001.md
/saqa diagnose RUN_20261104_xxx
/saqa jira inspect MED-101
/saqa jira process MED-101
```

---

## 5. Verifikasi Instalasi

Jalankan Hermes di terminal:
```bash
hermes
```

Ketik perintah plugin status di sesi Hermes:
```text
/plugins
```
Output yang diharapkan:
```text
Plugins:
  ✓ saqa v1.0.0 (5 tools, 1 commands)
```
