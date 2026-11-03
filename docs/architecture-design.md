# Desain Arsitektur: Hermes AI QA Agent & Google Docs Reporter

*Tanggal: 2026-11-03*  
*Workspace: `/root/dev/sangQA`*  
*Status Dokumen: Draft Spesifikasi Arsitektur (Menunggu Pengisian Prasyarat & Persetujuan)*

---

## 1. Ringkasan Eksekutif

Sistem otomasi pengujian browser berbasis AI Agent untuk tim QA izihealth yang memisahkan peran antara:
1. **Agent Harness (Hermes Agent)**: Antarmuka percakapan / CLI untuk membaca kasus uji, memicu pengujian, dan meninjau hasil evaluasi.
2. **Testing Engine (Playwright Runner)**: Pelaksana deterministik di peramban yang menangkap rekaman video WebM per skenario dan tangkapan layar pada titik kunci.
3. **Artifact & Docs Publisher**: Penyusun laporan pengujian terstruktur yang mengunggah bukti video ke Google Drive dan menerbitkan dokumen Google Docs dengan tangkapan layar tertanam privat.

---

## 2. Keputusan Arsitektur yang Telah Disepakati

| Komponen | Keputusan | Rasional |
| :--- | :--- | :--- |
| **Harness** | Hermes Agent CLI | Antarmuka otonom mandiri yang mudah dioperasikan oleh tim QA. |
| **Runner** | Adapter Playwright Test | Mendukung perekaman video per kasus uji (`video: 'on'`) dan isolasi konteks browser. |
| **Input Kasus Uji** | File Markdown di `test-cases/*.md` | Version-controlled, terstruktur, dan mudah dipelihara tim QA. |
| **Unit Laporan** | 1 Dokumen Google Docs per Test Case per Run | Berlaku untuk semua verdict (`PASSED`, `FAILED`, `BLOCKED`, `ERROR`) untuk riwayat audit terisolasi. |
| **Bukti Video** | File `.webm` diunggah ke Google Drive | Google Docs tidak mendukung pemutaran video native; tautan Drive disematkan di header dokumen. |
| **Bukti Tangkapan Layar** | Screenshot inline privat di Google Docs | Kandidat implementasi: kompilasi DOCX dengan gambar lokal yang diimpor ke Google Drive (`mimeType: application/vnd.google-apps.document`). |
| **Isolasi Kegagalan** | Pemisahan Verdict vs Status Publikasi | Kegagalan upload Google API tidak membatalkan verdict browser dan tidak memicu pengulangan aksi peramban. |
| **Cakupan Lingkungan** | Lingkungan Dev (Full Flow) | Menguji alur lengkap dengan data sintetis; backend dev terhubung ke sandbox/mock pihak ketiga. |

---

## 3. Alur Kerja Sistem (Pipeline Flow)

```
[test-cases/TC-xxx.md]
        │
        ▼
[Hermes Agent CLI / Adapter Runner]
        │
        ├── 1. Eksekusi Browser via Playwright
        │      ├── Navigasi & aksi halaman
        │      ├── Tangkap screenshot langkah kunci & titik asersi
        │      ├── Tutup konteks & simpan video.webm
        │      └── Tentukan Verdict: PASSED | FAILED | BLOCKED | ERROR
        │
        ├── 2. Simpan Artefak Lokal
        │      └── Direktori: artifacts/<run-id>/
        │          ├── video.webm
        │          ├── screenshots/
        │          ├── trace.zip
        │          └── metadata.json (verdict, step-by-step, timestamps)
        │
        └── 3. Publikasi Laporan (Bisa di-retry terpisah jika gagal)
               ├── Unggah video.webm ke Google Drive
               ├── Konversi laporan + screenshot lokal menjadi Google Docs
               └── Kembalikan tautan Google Docs & Drive ke terminal QA
```

---

## 4. Status Verifikasi Teknis & Batasan Kritis

1. **Jalur Gambar Privat Google Docs (Status: Kandidat Uji Coba):**
   - Google Docs API `InsertInlineImageRequest` mewajibkan URI publik.
   - Solusi tanpa hosting publik adalah menghasilkan file `.docx` lokal yang memuat screenshot biner, lalu mengunggahnya ke Google Drive API dengan konversi ke Google Docs (`application/vnd.google-apps.document`). Validitas resolusi gambar pada konversi ini wajib divalidasi lewat spike kecil sebelum penguncian modul publisher.
2. **Karakteristik Kuota Google Service Account:**
   - Google Service Account tidak memiliki kuota penyimpanan Google Drive independen.
   - Kredensial Service Account wajib ditautkan ke **Shared Drive (Google Workspace)** organisasi QA sebagai *Content Manager* / *Editor*, bukan folder My Drive personal biasa, untuk menghindari error kuota penyimpanan nol byte.
3. **Isolasi Mutasi Dev:**
   - Verifikasi bahwa backend dev izihealth secara riil mengarahkan gateway finansial dan SMS/WhatsApp ke mock/sandbox. Playwright hanya mengontrol sisi browser dan tidak memfilter mutasi yang dipicu server-side secara langsung.

---

## 5. Prasyarat & Konfigurasi Pilot Terpilih

Berdasarkan konfirmasi pengguna:
- **`DEV_BASE_URL`**: `https://dev-bcalife.izihealth.co.id/`
- **Skenario Pilot (TC-001)**: Login staf dengan kredensial valid ke dashboard Managed Care.
  - *Prasyarat Kredensial*: Disimpan dalam environment variable (`QA_USERNAME` dan `QA_PASSWORD`), dilarang keras dicatat secara terbuka (*plaintext*) di kode sumber, dokumen Markdown, log, atau artefak publik.
  - *Kriteria Kelulusan (PASS)*: Elemen judul/menu dashboard "Managed Care" terbukti termuat pada antarmuka, bukan sekadar hilangnya form login atau perubahan URL semata.
  - *Mitigasi Privasi Bukti*: Input kata sandi dimasking pada browser; screenshot fokus pada antarmuka umum dan hasil dashboard pasca-login.

### Konfigurasi Google Drive (Menunggu Input):
- **`GOOGLE_DRIVE_FOLDER_ID`**: ID Shared Drive / folder Google Drive tim QA (belum diisi).
- **Kredensial Service Account**: `credentials/service-account.json` (belum diisi; sistem akan mencatat status pelaporan sebagai `UNPUBLISHED` secara aman jika file ini belum tersedia).
