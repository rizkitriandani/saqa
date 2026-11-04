---
description: SAQA AI QA Automation (config, authoring, audit, runner, diagnose)
argument-hint: "[config | run <path> | approve <path> | audit <path> | diagnose <run_id> | list]"
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

2. Jika argumen diawali dengan "audit":
   Ambil path berkas kasus uji dari argumen kedua.
   Lakukan audit pra-eksekusi terhadap berkas tersebut:
   a. Periksa kepatuhan kontrak tabel Test Steps dan Expected Results.
   b. Evaluasi kelogisan alur, kemungkinan selektor ambigu, dan kelengkapan prasyarat.
   c. Sajikan saran perbaikan dan tawarkan pembaruan langsung pada berkas draf.

3. Jika argumen diawali dengan "approve":
   Ambil path berkas kasus uji dari argumen kedua.
   Jalankan pengesahan hash kanonikal:
   `python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" approve "$2" --project-root .`

4. Jika argumen diawali dengan "run":
   Ambil path berkas kasus uji dari argumen kedua. Periksa apakah kasus uji sudah disetujui (memiliki `Approval Hash`).
   Jalankan:
   `python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" run "$2" --project-root . --no-publish`
   Jika hasil pengujian FAILED atau BLOCKED, otomatis lanjutkan dengan alur diagnose pada Run ID terkait.

5. Jika argumen diawali dengan "diagnose":
   Ambil Run ID dari argumen kedua.
   Jalankan diagnostik pasca-eksekusi:
   a. Panggil helper diagnostik: `python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" diagnose "$2" --project-root .`
   b. Periksa tangkapan layar kegagalan menggunakan tool visual `read`.
   c. Sajikan analisis akar masalah (root cause) kepada operator manusia dan sematkan ke laporan jika disetujui:
      `python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" diagnose "$2" --attach "<ringkasan_analisis>" --project-root .`

6. Jika argumen adalah "list":
   Tampilkan riwayat pengujian proyek aktif:
   `python3 "${SAQA_ROOT:-/root/dev/sangQA}/cli.py" list --project-root .`

7. Untuk instruksi lainnya:
   Layani penyusunan draf kasus uji bahasa alami sesuai panduan di skill `saqa`. Simpan draf dengan status `pending` dan minta review manusia sebelum disetujui.
