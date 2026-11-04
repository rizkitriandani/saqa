---
description: SAQA AI QA Automation (onboarding / config, authoring, runner)
argument-hint: "[config | run <path> | approve <path> | list]"
---
Muat skill `saqa`. Argumen perintah yang diterima: "${@:-config}".

Jika argumen adalah "config" atau diawali dengan "config":
Pandu operator manusia melakukan konfigurasi SAQA untuk PROYEK AKTIF di direktori kerja saat ini:
1. Konfirmasi direktori kerja saat ini (`pwd`) sebagai root proyek.
2. Tanyakan secara ringkas:
   - **Project ID / slug**: (default: nama folder saat ini)
   - **Target Dev Base URL**: URL web staging yang akan diuji
   - **Output Google Drive**: Apakah ingin mengaktifkan ekspor video & Google Docs? (Catatan: Input dari Jira dan Google Docs watcher berstatus roadmap tahap berikutnya).
3. Tampilkan ringkasan data konfigurasi dan minta konfirmasi operator sebelum menyimpan.
4. Setelah disetujui, eksekusi perintah:
   ```bash
   python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" config --project-root . --project-id "<id>" --base-url "<url>" [--gdrive]
   ```
5. Ingatkan operator untuk melengkapi kredensial akun uji di file `.env` lokal berdasarkan `.env.example`. **JANGAN PERNAH meminta operator mengetikkan password di dalam chat.**

Jika argumen diawali dengan "run":
Periksa apakah kasus uji sudah disetujui. Jalankan:
```bash
python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" run "$2" --project-root . --no-publish
```

Jika argumen diawali dengan "approve":
Jalankan pengesahan hash kanonikal:
```bash
python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" approve "$2" --project-root .
```

Jika argumen adalah "list":
Tampilkan riwayat pengujian proyek aktif:
```bash
python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" list --project-root .
```

Untuk instruksi lainnya, layani penyusunan draf kasus uji bahasa alami sesuai panduan di skill `saqa`.
