# Panduan Integrasi: Jira Cloud Automation ke GitHub Actions Runner

*Tanggal: 2026-11-04*  
*Workspace: `/root/dev/sangQA`*  
*Target Instance: `https://medlinx.atlassian.net`*

Dokumen ini menjelaskan langkah demi langkah cara mengonfigurasi otomatisasi di Jira Cloud agar ketika kartu tiket dipindahkan statusnya (misal ke `In Testing` atau `In QA`), Jira secara otomatis memicu pengujian browser di GitHub Actions, lalu menerima lampiran laporan DOCX, video WebM, dan komentar hasil pengujian.

---

## 1. Prasyarat Kredensial & Secrets di GitHub

Sebelum membuat aturan di Jira, pastikan secrets telah ditambahkan pada repositori GitHub Anda (**Settings → Secrets and variables → Actions → New repository secret**):

| Secret Name | Deskripsi | Contoh Nilai |
| :--- | :--- | :--- |
| `DEV_BASE_URL` | URL target lingkungan staging izihealth | `https://dev-bcalife.izihealth.co.id/` |
| `QA_USERNAME` | Akun staf uji coba staging | `superuser` |
| `QA_PASSWORD` | Kata sandi akun uji coba | `********` |
| `JIRA_BASE_URL` | URL dasar Jira Cloud Anda | `https://medlinx.atlassian.net` |
| `JIRA_EMAIL` | Email akun Atlassian pengunggah laporan | `qa@medlinx.id` |
| `JIRA_API_TOKEN` | API Token Jira ([Buat di sini](https://id.atlassian.com/manage-profile/security/api-tokens)) | `ATATT3xFfGF0...` |
| `GOOGLE_DRIVE_FOLDER_ID` *(Opsional)* | ID folder Shared Drive jika ingin upload ke Drive | `1Z68ydb1eCc0...` |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` *(Opsional)* | Isi teks JSON Service Account untuk Drive | `{"type": "service_account", ...}` |

---

## 2. Buat GitHub Personal Access Token (PAT) untuk Jira

Jira Automation membutuhkan Personal Access Token GitHub untuk mengirimkan webhook `repository_dispatch`:

1. Buka akun GitHub Anda: **Settings → Developer Settings → Personal access tokens → Fine-grained tokens** (atau Tokens classic).
2. Klik **Generate new token**.
3. Beri nama: `jira-automation-trigger`.
4. Berikan izin:
   - Jika Classic Token: centang scope `repo`.
   - Jika Fine-grained: pilih repository `rizkitriandani/saqa` dan berikan izin **Contents: Read and Write** (atau `Repository dispatch`).
5. Simpan dan salin token tersebut (contoh: `ghp_xxxxxxxxxxxx`).

---

## 3. Konfigurasi Aturan Otomatisasi di Jira Cloud

Buka board proyek Anda di `https://medlinx.atlassian.net`:

1. Klik menu **Project settings** (di sidebar kiri bawah) → pilih **Automation**.
2. Klik tombol **Create rule** di pojok kanan atas.

### A. Atur Trigger (Pemicu)
1. Pilih trigger: **Issue transitioned**.
2. Kolom **From status**: Biarkan kosong (*Leave blank for any status*).
3. Kolom **To status**: Pilih status pengujian tim Anda (misal: `In Testing`, `In QA`, atau `Ready for QA`).
4. Klik **Save**.

### B. Atur Condition (Filter Tiket - Rekomendasi)
Agar otomatisasi hanya berjalan pada tiket yang memang memiliki kasus uji:
1. Klik **Add component** → pilih **Issue fields condition**.
2. Field: `Description`
3. Condition: `contains`
4. Value: `Test Cases` (atau `QA Scenario`)
5. Klik **Save**.

### C. Atur Action: Send web request
1. Klik **Add component** → pilih **Send web request**.
2. **Web request URL**:
   ```text
   https://api.github.com/repos/rizkitriandani/saqa/dispatches
   ```
3. **HTTP method**: `POST`
4. **Web request headers**:
   - `Accept`: `application/vnd.github.v3+json`
   - `Authorization`: `Bearer ghp_token_github_anda_di_sini`
   - `Content-Type`: `application/json`
5. **Web request body**: Pilih opsi **Custom data**
6. Masukkan payload JSON berikut:
   ```json
   {
     "event_type": "jira-trigger",
     "client_payload": {
       "issue_key": "{{issue.key}}",
       "project_id": "saqa"
     }
   }
   ```
7. Centang opsi: **Wait for response** (opsional) atau biarkan *fire-and-forget*.
8. Klik **Save**.

### D. Publikasikan Aturan
1. Beri nama aturan: `SAQA - Auto E2E Browser Testing`.
2. Klik tombol **Turn on rule**.

---

## 4. Alur Eksekusi Otomatis

Setelah aturan aktif:
1. Pengembang atau QA menggeser kartu tiket (misal `MED-101`) ke status `In Testing`.
2. Jira mengirimkan web request ke GitHub Actions repository dispatch.
3. Workflow GitHub Actions (`.github/workflows/saqa-jira.yml`) menyala otomatis:
   - Menjalankan Playwright di lingkungan Ubuntu cloud.
   - Mengambil rekaman video WebM dan screenshot.
   - Menyusun laporan DOCX.
4. Runner mengirimkan hasil langsung ke kartu `MED-101`:
   - Melampirkan `report.docx` dan `evidence.webm` ke attachment tiket.
   - Menuliskan komentar ringkasan dengan badge status (`(/) *PASSED*` atau `(x) *FAILED*`).
5. Seluruh artefak pengujian juga tersimpan di tab **Actions** GitHub selama 14 hari.
