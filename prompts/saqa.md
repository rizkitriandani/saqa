---
description: SAQA AI QA Automation (onboarding / config, authoring, runner)
argument-hint: "[config | run <path> | approve <path> | list]"
---
Muat skill `saqa`. Argumen perintah yang diterima: "${@:-config}".

Tentukan aksi berdasarkan argumen yang diberikan:

1. Jika argumen adalah "config" atau diawali dengan "config":
   Pandu operator manusia melakukan onboarding konfigurasi SAQA untuk PROYEK AKTIF di direktori kerja saat ini:
   a. Konfirmasi direktori kerja saat ini (`pwd`) sebagai root proyek.
   b. Tanyakan secara ringkas:
      - **Project ID / slug**: (default: nama folder saat ini)
      - **Target Dev Base URL**: URL web staging yang akan diuji
      - **Output Google Drive**: Apakah ingin mengaktifkan ekspor video & Google Docs? (Catatan: Input dari Jira dan Google Docs watcher berstatus roadmap tahap berikutnya).
   c. Tampilkan ringkasan data konfigurasi dan minta konfirmasi operator manusia sebelum menyimpan.
   d. Setelah disetujui manusia, eksekusi perintah pembuatan konfigurasi melalui CLI:
      `python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" config --project-root . --project-id "<id>" --base-url "<url>" [--gdrive]`
   e. Ingatkan operator untuk mengisi kredensial di file `.env` lokal berdasarkan `.env.example`. **JANGAN PERNAH meminta operator mengetikkan password di dalam chat.**

2. Jika argumen diawali dengan "run":
   Ambil path berkas kasus uji dari argumen. Periksa apakah kasus uji sudah disetujui (memiliki `Approval Hash`).
   Jalankan:
   `python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" run "<path>" --project-root . --no-publish`

3. Jika argumen diawali dengan "approve":
   Ambil path berkas kasus uji dari argumen.
   Jalankan pengesahan hash kanonikal:
   `python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" approve "<path>" --project-root .`

4. Jika argumen adalah "list":
   Tampilkan riwayat pengujian proyek aktif:
   `python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" list --project-root .`

5. Untuk instruksi lainnya:
   Layani penyusunan draf kasus uji bahasa alami sesuai panduan di skill `saqa`. Simpan draf dengan status `pending` dan minta review manusia sebelum disetujui.
