# Rencana Perbaikan & Pengerasan Core Runner (Core Hardening Plan)

*Tanggal: 2026-11-03*  
*Workspace: `/root/dev/sangQA`*  
*Status: Rencana Kerja Implementasi Pilot C*

---

## 1. Latar Belakang Masalah

Pada implementasi awal, `runner/engine.py` berhasil menjalankan kasus login BCA Life, namun masih memiliki keterbatasan arsitektural:
1. **Asersi Hardcoded**: Evaluasi kelulusan akhir masih memeriksa teks spesifik dashboard BCA Life ("Care Monitor", "Total Member", dsb.). Skenario pengujian lain akan dinilai menggunakan heuristik login ini sehingga menimbulkan potensi *false-pass* atau *false-fail*.
2. **Targeting Rawan Ambigu**: Penggunaan `.first` dan fallback generik berisiko mengklik elemen yang salah jika ada lebih dari satu tombol atau kolom di halaman.
3. **Kebocoran Environment**: Fungsi substitusi variabel saat ini menggantikan seluruh variabel di `.env`, yang berisiko mengekspos token Google API ke input peramban jika ada placeholder yang tidak disengaja.
4. **Approval Gate Teks Biasa**: Header `Approval Status: approved` dapat ditulis sendiri oleh siapapun atau dihasilkan AI tanpa jaminan integritas konten.

---

## 2. Spesifikasi Desain Pengerasan Core

### A. Validasi Parser Ketat (*Fail-Closed Validation*)
- **Penolakan Mode Belum Didukung**: Kasus uji dengan `Execution Mode: ai` langsung ditolak dengan pesan error jelas sebelum peramban dibuka.
- **Validasi Langkah**: Nomor langkah wajib berurutan, kolom aksi wajib berupa kata kerja baku (`navigate`, `fill`, `click`, `select`, `wait`, `assert`).
- **Allowlist Variabel**: Hanya variabel yang diizinkan (`DEV_BASE_URL`, `QA_USERNAME`, `QA_PASSWORD`) yang disubstitusi. Variabel di luar allowlist ditolak.
- **Allowlist Origin**: Aksi `navigate` hanya diizinkan ke origin domain yang terdaftar (origin `DEV_BASE_URL` atau domain pengujian resmi).

### B. Asersi Generik Berbasis Aturan (*Generic Assertions Engine*)
Menggantikan heuristik login hardcoded dengan parser aturan asersi yang mendukung:
- **Pemeriksaan URL**:
  - `url does not contain "/login"`
  - `url contains "dashboard"`
  - `url equals "<expected_url>"`
- **Pemeriksaan Visibilitas Teks / Elemen**:
  - `text contains "Welcome Back"`
  - `element "<selector/label>" is visible`
  - `heading contains "Dashboard"`
- **Prinsip Fail-Closed**: Jika ada baris `Expected Results` yang tidak dapat dipetakan secara terukur oleh mesin asersi, eksekusi **dibatalkan sebelum browser diluncurkan**.

### C. Penargetan Elemen Unik (*Unambiguous Targeting*)
- Menghapus ketergantungan pada `.first` tanpa verifikasi.
- Jika sebuah target label menghasilkan lebih dari 1 elemen aktif (`count > 1`) dan tidak ada spesifikasi unik, runner melempar error `AmbiguousTargetError` agar kasus uji diperjelas, bukan menebak elemen sembarang.

### D. Approval Gate Berbasis Content Hash
- Mengikat status persetujuan dengan **SHA-256 Content Hash**:
  - Hash dihitung dari representasi kanonikal kasus uji (semua baris selain `Approval Status` dan `Approval Hash`).
  - Perintah `python3 cli.py approve <path>` menghitung hash dan menuliskan metadata:
    ```markdown
    - **Approval Status**: approved
    - **Approval Hash**: <sha256-hex>
    ```
  - Saat `cli.py run` dijalankan, engine menghitung ulang hash konten saat itu. Jika ada perubahan 1 karakter pun pada langkah atau ekspektasi, hash tidak cocok dan eksekusi otomatis **`BLOCKED`**.
  - *Batasan Keamanan*: Mekanisme ini mencegah perubahan tak sengaja pada kasus uji yang sudah disetujui di level lokal. Proteksi otentikasi reviewer sejati membutuhkan sistem autentikasi multi-user terpisah.

---

## 3. Rencana Pengujian TDD (Offline Test Suite)

Sebelum mengubah kode produksi, buat test suite offline di `tests/test_core_engine.py` menggunakan fixture HTML lokal (tanpa akses internet):
1. `test_ai_mode_rejected_fail_closed`: Menolak mode `ai`.
2. `test_unsupported_expected_result_rejected`: Menolak ekspektasi yang tidak dapat dikompilasi sebelum peramban dibuka.
3. `test_content_hash_invalidation`: Memastikan perubahan langkah menggugurkan approval.
4. `test_ambiguous_target_rejected`: Memastikan target ambigu tidak diklik sembarangan.
5. `test_generic_assertions_pass_and_fail`: Menguji evaluasi asersi generik (`url contains`, `text contains`) pada halaman HTML fixture lokal.
