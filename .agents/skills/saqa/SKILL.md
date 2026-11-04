---
name: saqa
description: End-to-end browser QA automation and test case authoring. Use when creating test cases from natural language, running E2E web tests, validating UI flows, or publishing test reports to Google Docs/Drive.
---

# SAQA: AI QA Automation Skill

Sistem panduan bagi agen AI (Pi Coding Agent, Hermes, Claude Code) untuk berinteraksi dengan tim QA, menyusun spesifikasi Kasus Uji baku dari bahasa alami, menegakkan persetujuan manusia (*Approval Gate*), dan mengeksekusi pengujian peramban Playwright melalui Core CLI.

---

## 1. Peran & Tanggung Jawab Agen

Sebagai asisten QA, tugas Anda adalah:
1. **Mendengarkan Skenario QA**: Membaca instruksi pengujian dalam bahasa alami bebas (Indonesia atau Inggris).
2. **Klarifikasi Ambiguitas**: Jika target aksi, halaman, atau kriteria kelulusan belum jelas, ajukan pertanyaan singkat sebelum menyusun draf.
3. **Menyusun Draf Kasus Uji**: Terjemahkan ke berkas Markdown terstruktur sesuai kontrak baku di `docs/test-case-contract.md`.
4. **Menegakkan Approval Gate**: Selalu setel status awal draf sebagai `pending`. **DILARANG menyetujui draf buatan sendiri secara sepihak.** Minta konfirmasi eksplisit dari operator manusia.
5. **Mengeksekusi CLI**: Setelah disetujui manusia via `cli.py approve`, panggil `python3 cli.py run <path>` untuk menjalankan browser dan melaporkan hasil.

---

## 2. Aturan Keamanan & Batasan Kritis (Security Invariants)

- **Jangan Pernah Meminta Password**: Dilarang meminta operator mengetikkan kata sandi di chat atau tiket. Gunakan selalu placeholder referensi seperti `${QA_USERNAME}` dan `${QA_PASSWORD}`.
- **Batasan Substitusi Rahasia**: Kata sandi `${QA_PASSWORD}` hanya boleh digunakan pada kolom input form/fill; dilarang keras ditaruh pada URL navigasi atau teks terbuka.
- **Fail-Closed Execution**: Runner akan menolak kasus uji yang memuat aturan asersi tidak terukur, origin di luar allowlist, atau mode yang belum didukung (`ai`).
- **Verifikasi Sebelum Klaim Sukses**: Jangan pernah menyatakan pengujian berhasil tanpa bukti eksekusi zero-failure pada giliran saat ini.

---

## 3. Format Kontrak Kasus Uji Baku

Setiap kasus uji wajib disimpan di direktori `test-cases/<TC-ID>-<slug>.md` dengan format berikut:

```markdown
# {ID}: {Title}

- **ID**: {Unique ID, misal: TC-002}
- **Title**: {Deskripsi singkat skenario uji}
- **Type**: {Positive | Negative | Boundary}
- **Execution Mode**: deterministic
- **Approval Status**: pending
- **Target URL**: ${DEV_BASE_URL}
- **Account**: ${QA_USERNAME}

## Preconditions
- {Prasyarat sebelum pengujian berjalan}

## Test Data
- username: ${QA_USERNAME}
- password: ${QA_PASSWORD}

## Test Steps
| Step | Action   | Target Element / Label   | Input Value      | Expected Step Outcome                       |
| :--- | :------- | :----------------------- | :--------------- | :------------------------------------------ |
| 1    | navigate | ${DEV_BASE_URL}          | -                | Halaman target berhasil termuat             |
| 2    | fill     | {Label / Placeholder}    | {Value}          | Kolom terisi data                           |
| 3    | click    | {Tombol / Teks Elemen}   | -                | Aksi diproses                               |

## Expected Results
- url does not contain "/login"
- heading contains "{Teks Heading}"
- text contains "{Teks Yang Wajib Muncul}"
- element "{CSS Selector}" is visible
```

### Aturan Kolom Action:
Gunakan kata kerja mesin baku: `navigate`, `fill`, `click`, `select`, `wait`, `assert`.

### Aturan Expected Results (Strict Machine Grammar):
Setiap baris wajib menggunakan format gramar terukur dengan tanda kutip:
- `url contains "..."` atau `url does not contain "..."` atau `url equals "..."`
- `heading contains "..."`
- `text contains "..."`
- `element "..." is visible`

---

## 4. Alur Kerja Langkah Demi Langkah (Workflow)

### Langkah 1: Wawancara & Pembuatan Draf (Conversational Grilling)
Ketika pengguna meminta menguji sebuah alur atau sistem menerima notifikasi tiket Jira yang belum siap dieksekusi:
1. **Lakukan Grilling Proaktif**: Ajukan pertanyaan satu per satu untuk memperjelas:
   - Apa target halaman dan modul fitur yang diuji?
   - Akun/role pengguna apa yang digunakan?
   - Apa urutan aksi spesifik (klik tombol apa, isi input apa)?
   - Apa kriteria hasil terukur yang menentukan kelulusan?
2. Tulis draf berkas kasus uji di `test-cases/TC-xxx.md` (atau `test-cases/drafts/<KEY>-scenario.md`).
3. Pastikan header memuat:
   ```markdown
   - **Execution Mode**: deterministic
   - **Approval Status**: pending
   ```
4. Tampilkan ringkasan langkah dan kriteria kelulusan kepada pengguna.

### Langkah 2: Review & Approval Gate
Tanyakan kepada operator manusia:
> *"Draf kasus uji `test-cases/TC-xxx.md` telah dibuat dengan status `pending`. Apakah langkah dan kriteria di atas sudah sesuai? Jika setuju, jalankan `python3 cli.py approve test-cases/TC-xxx.md` untuk mengesahkannya."*

Jika pengguna meminta audit/cross-check terlebih dahulu:
1. Periksa kelogisan alur: Apakah langkah prasyarat masuk akal?
2. Periksa selektor: Apakah target ambigu atau terlalu umum?
3. Periksa asersi: Apakah kriteria hasil memenuhi gramar mesin baku (`url contains`, `heading contains`, `text contains`, `element is visible`)?
4. Berikan saran perbaikan dan perbarui berkas kasus uji agar siap disetujui.

Jika pengguna memberikan konfirmasi verbal *"Approve & Run"* di chat, agen dapat mengeksekusi persetujuan dan peluncuran secara atomik:
```bash
python3 cli.py approve test-cases/TC-xxx.md && python3 cli.py run test-cases/TC-xxx.md --no-publish
```

### Langkah 3: Eksekusi Pengujian
Jalankan pengujian menggunakan CLI runner:
```bash
python3 cli.py run test-cases/TC-xxx.md --no-publish
```

### Langkah 4: Pelaporan Hasil & Diagnostik Kegagalan
Baca output eksekusi dan sajikan ke pengguna:
- **Verdict**: `PASSED` / `FAILED` / `BLOCKED` / `ERROR`.
- **Keterangan**: Hasil evaluasi aktual.

**Jika Hasil Pengujian `FAILED` atau `BLOCKED` (AI Failure Diagnostics)**:
1. Panggil helper diagnostik:
   ```bash
   python3 cli.py diagnose <RUN_ID>
   ```
2. Baca berkas tangkapan layar kegagalan (`failure_screenshot_path`) menggunakan tool visual `read`.
3. Analisis antarmuka web pada titik kegagalan:
   - Apakah ada alert merah (misal: "Username or Password incorrect", "Account locked")?
   - Apakah tombol dalam keadaan disabled?
   - Apakah kolom formulir belum terisi lengkap?
4. Rumuskan analisis akar masalah (*Root Cause Analysis*) dalam bahasa manusia yang ramah, dan sematkan ke dalam laporan:
   ```bash
   python3 cli.py diagnose <RUN_ID> --attach "Analisis AI: <penjelasan_akar_masalah_dan_saran>"
   ```
5. Berkas laporan DOCX akan otomatis diperbarui dan komentar Jira (jika aktif) akan menyertakan analisis tersebut.

---

## 5. Resolusi Lokasi Repository & Perintah CLI

Skill ini dapat dijalankan dari direktori kerja mana pun. Agen harus menyelesaikan lokasi root repositori `sangQA`:
1. Cek environment variable `SAQA_ROOT` jika disetel.
2. Cek apakah direktori kerja saat ini adalah root `sangQA` (memiliki file `cli.py`).
3. Gunakan path instalasi standar: `/root/dev/sangQA`.

Contoh eksekusi:
- **Konfigurasi Proyek**: `python3 <SAQA_ROOT>/cli.py config --project-root .`
- **Validasi Kesiapan Tiket Jira**: `python3 <SAQA_ROOT>/cli.py jira validate <ISSUE_KEY> --project-root .`
- **Setujui Uji**: `python3 <SAQA_ROOT>/cli.py approve <path_to_test_case.md> --project-root .`
- **Jalankan Uji**: `python3 <SAQA_ROOT>/cli.py run <path_to_test_case.md> --no-publish --project-root .`
- **Diagnosa Run**: `python3 <SAQA_ROOT>/cli.py diagnose <run_id> [--attach "<analysis>"] --project-root .`
- **Jalankan Webhook Server (VPS Listener)**: `python3 <SAQA_ROOT>/cli.py webhook --port 8080 --runner local --project-root .`
- **Publikasikan**: `python3 <SAQA_ROOT>/cli.py publish <run_id> --project-root .`
- **Lihat Riwayat**: `python3 <SAQA_ROOT>/cli.py list --project-root .`
