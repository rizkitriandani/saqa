# Kontrak Spesifikasi Kasus Uji & Arsitektur Adapter Pihak Ketiga

*Tanggal: 2026-11-03*  
*Workspace: `/root/dev/sangQA`*  
*Status: Spesifikasi Standar Disetujui (Status Implementasi: Kontrak Disepakati, Parser Langkah Dinamis & Adapter Jira Belum Dibangun)*

---

## 0. Status Kesiapan Implementasi Saat Ini

- **Kontrak Spesifikasi**: Disepakati dan menjadi rujukan baku penulisan kasus uji tim QA.
- **Engine Saat Ini (`runner/engine.py`)**: Mengeksekusi alur login valid BCA Life secara terverifikasi. Parser Markdown saat ini membaca metadata `ID` dan `Title`. Parser langkah dinamis dari tabel Markdown, adapter webhook Jira, serta integrasi orkestrator Hermes/Vision berstatus **tahap pengembangan berikutnya**.
- **Karakteristik Asersi**: Teks narasi bebas pada `Expected Results` tidak otomatis menjadi kode asersi peramban; adapter dan runner wajib memvalidasi target elemen secara ketat dan menolak instruksi yang ambigu. Pendekatan deterministik meminimalkan ketidakpastian tetapi tetap memerlukan penanganan latensi jaringan peramban.

---

## 1. Arsitektur Decoupled: Ports & Adapters (Hexagonal)

Untuk mencegah keterikatan vendor (*vendor lock-in*) pada sistem pelacak tiket tertentu (seperti Jira), sistem menggunakan arsitektur *Ports & Adapters*:

```
[Sumber Trigger Pihak Ketiga]
   ├── Jira Cloud / Data Center Webhook
   ├── GitHub Actions / GitLab CI Webhook
   └── Operator CLI Manual (cli.py)
              │
              ▼ [Port Masukan: Trigger Ingestion]
   ┌────────────────────────────────────────────────────────┐
   │ 1. Trigger Adapter (Third-Party Specific)              │
   │    • Validasi signature & otentikasi webhook           │
   │    • Ekstraksi konteks (Issue Key, Trigger Status)     │
   │    • Normalisasi Kasus Uji (Git Ref atau Inline MD)    │
   │    • Idempotency Gate (Cegah duplikasi eksekusi)       │
   └──────────────────────────┬─────────────────────────────┘
                              │
                              ▼ [Kontrak DTO Netral Vendor]
   ┌────────────────────────────────────────────────────────┐
   │ 2. Core Automation Engine (Pure Domain)                │
   │    • Validasi skema langkah Kasus Uji                  │
   │    • Eksekusi Browser via Playwright                   │
   │      - Mode "deterministic": Aksi & asersi baku        │
   │      - Mode "ai": Navigasi model visual + asersi baku  │
   │    • Perekaman video utuh & tangkapan layar per langkah│
   │    • Penentuan Verdict objektif                        │
   └──────────────────────────┬─────────────────────────────┘
                              │
                              ▼ [Port Keluaran: Reporter]
   ┌────────────────────────────────────────────────────────┐
   │ 3. Artifact & Publisher Subsystem                      │
   │    • Penyusunan laporan DOCX dengan screenshot privat  │
   │    • Pengunggahan video & konversi Google Docs         │
   │    • Pengelompokan folder per run di Shared Drive      │
   └──────────────────────────┬─────────────────────────────┘
                              │
                              ▼ [Port Keluaran: Response Notification]
   ┌────────────────────────────────────────────────────────┐
   │ 4. Feedback Adapter (Third-Party Specific)             │
   │    • Jira REST API: Kirim komentar & tautan bukti      │
   │    • GitHub / GitLab: Kirim Commit Status / PR Comment │
   │    • CLI: Cetak ringkasan ke terminal                  │
   └────────────────────────────────────────────────────────┘
```

---

## 2. Format Baku Kasus Uji (English Field Names)

Semua nama field dan heading wajib menggunakan bahasa Inggris baku, sedangkan konten isian bebas menggunakan bahasa Indonesia maupun bahasa Inggris.

### Template Spesifikasi Kasus Uji (.md)

```markdown
# {ID}: {Title}

- **ID**: {Unique Case ID, misal: TC-001}
- **Title**: {Deskripsi singkat skenario uji}
- **Type**: {Positive | Negative | Boundary}
- **Execution Mode**: {deterministic | ai}   <!-- Default: deterministic -->
- **Target URL**: ${DEV_BASE_URL}
- **Account**: ${QA_USERNAME}                <!-- Kredensial rahasia tetap di server env -->

## Preconditions
- {Daftar prasyarat sebelum pengujian dijalankan}

## Test Data
- {parameter_1}: {value}
- {parameter_2}: {value}

## Test Steps
| Step | Action   | Target Element / Label   | Input Value      | Expected Step Outcome                       |
| :--- | :------- | :----------------------- | :--------------- | :------------------------------------------ |
| 1    | navigate | ${DEV_BASE_URL}          | -                | Halaman target berhasil termuat             |
| 2    | fill     | {Field Label / Target}   | {Input Value}    | Kolom terisi data                           |
| 3    | click    | {Button / Element Text}  | -                | Permintaan aksi diproses                    |

## Expected Results
- {Kriteria keberhasilan terukur 1}
- {Kriteria keberhasilan terukur 2}
- {Indikator asersi UI atau data yang wajib tampil}
```

---

## 3. Aturan Standar Kolom Langkah (Test Steps Contract)

### Kata Kunci Aksi (Machine Enums)
Kolom `Action` wajib menggunakan kata kerja standar berikut:
- **`navigate`**: Membuka URL target (`Target Element` = URL).
- **`fill`**: Mengisi kolom input teks / textarea (`Target Element` = Label teks, placeholder, atau nama kolom; `Input Value` = teks yang diisikan).
- **`click`**: Mengklik elemen interaktif (`Target Element` = Teks tombol, link, atau label radio/checkbox).
- **`select`**: Memilih opsi pada dropdown / select list (`Target Element` = Label dropdown; `Input Value` = Teks opsi yang dipilih).
- **`wait`**: Menunggu status tertentu (`Target Element` = Indikator elemen / waktu; `Input Value` = durasi/kondisi).
- **`assert`**: Memeriksa keberadaan elemen atau teks tertentu secara eksplisit di langkah perantara.

---

## 4. Batasan Mode Eksekusi (Execution Mode)

1. **Mode `deterministic` (Default)**:
   - Runner memetakan setiap baris tabel langkah secara langsung ke aksi Playwright berdasarkan label antarmuka yang cocok.
   - Memberikan kecepatan maksimal, deterministik, dan bebas biaya token visual model.
2. **Mode `ai` (Fitur Opsional)**:
   - Dinyatakan secara eksplisit via `Execution Mode: ai`.
   - Agen visual (Hermes / Vision AI) menganalisis tata letak halaman dan mencari elemen interaktif secara dinamis tanpa bergantung pada selektor kaku.
   - **Batas Kritis**: Asersi akhir kelulusan (`PASSED`) tetap wajib memvalidasi kriteria pada field `Expected Results` yang didefinisikan QA. AI tidak diizinkan meloloskan pengujian tanpa verifikasi kriteria tersebut.
   - Tidak ada *silent fallback* dari mode deterministik ke mode AI jika terjadi kegagalan.

---

## 5. Sumber Kasus Uji Hybrid pada Jira

1. **Referensi Kasus Uji Git**:
   Di kartu Jira, tim QA cukup mencantumkan:
   ```text
   Test Cases:
   - TC-001
   - TC-002
   ```
   Adapter akan memuat file `test-cases/TC-001-*.md` dan `test-cases/TC-002-*.md` dari repositori.

2. **Inline Kasus Uji Baru**:
   Jika skenario belum di-commit ke Git, tim QA dapat menempelkan blok Markdown mengikuti template di atas langsung di dalam deskripsi kartu Jira. Adapter akan mengekstrak blok tersebut, menyimpan **snapshot kasus uji bersama artefak eksekusi** di `artifacts/<run-id>/test-case-snapshot.md` (tanpa menyertakan nilai rahasia), dan menjalankannya sehingga hasil pengujian tetap dapat diaudit dan direproduksi meskipun kartu Jira mengalami perubahan di kemudian hari.
