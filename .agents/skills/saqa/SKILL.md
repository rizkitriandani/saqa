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

### Langkah 1: Wawancara & Pembuatan Draf
Ketika pengguna meminta menguji sebuah alur (misal: *"Tolong buatkan test login admin"*):
1. Tulis draf berkas kasus uji di `test-cases/TC-xxx.md`.
2. Pastikan header memuat:
   ```markdown
   - **Execution Mode**: deterministic
   - **Approval Status**: pending
   ```
3. Tampilkan ringkasan langkah dan kriteria kelulusan kepada pengguna.

### Langkah 2: Review & Approval Gate
Tanyakan kepada operator manusia:
> *"Draf kasus uji `test-cases/TC-xxx.md` telah dibuat dengan status `pending`. Apakah langkah dan kriteria di atas sudah sesuai? Jika setuju, jalankan `python3 cli.py approve test-cases/TC-xxx.md` untuk mengesahkannya."*

Jika pengguna memberikan konfirmasi verbal setuju, agen dapat mengeksekusi perintah persetujuan:
```bash
python3 cli.py approve test-cases/TC-xxx.md
```
*(Perintah ini menghitung SHA-256 hash kanonikal dan menyematkan `Approval Hash` ke berkas).*

### Langkah 3: Eksekusi Pengujian
Jalankan pengujian menggunakan CLI runner:
```bash
python3 cli.py run test-cases/TC-xxx.md
```
*(Tambahkan `--no-publish` jika pengguna hanya ingin pengujian lokal tanpa unggah Google Drive).*

### Langkah 4: Pelaporan Hasil
Baca output eksekusi dan sajikan ke pengguna:
- **Verdict**: `PASSED` / `FAILED` / `BLOCKED` / `ERROR`.
- **Keterangan**: Hasil evaluasi aktual.
- **Tautan Bukti Google Docs**: Link dokumen laporan jika berhasil diunggah.
- **Tautan Bukti Video**: Link rekaman video WebM di Google Drive.

---

## 5. Perintah CLI Referensi

- **Jalankan Uji**: `python3 cli.py run <path_to_test_case.md>`
- **Setujui Uji**: `python3 cli.py approve <path_to_test_case.md>`
- **Publikasi Ulang**: `python3 cli.py publish <run_id>`
- **Lihat Riwayat**: `python3 cli.py list`
