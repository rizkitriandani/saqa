!# AI QA Automation

Sistem otomasi pengujian browser berbasis agen untuk tim QA izihealth.

## Language

**Kasus Uji**:
Dokumen spesifikasi skenario pengujian yang mendefinisikan prasyarat, langkah aksi pengguna, dan kriteria hasil yang diharapkan.
_Avoid_: Test script, test scenario, test spec

**Eksekusi Kasus Uji**:
Satu siklus penjalanan Kasus Uji pada peramban web dari status awal hingga menghasilkan status akhir.
_Avoid_: Test job, test session, batch run

**Hasil Pengujian**:
Status evaluasi akhir atas Eksekusi Kasus Uji terhadap kriteria keberhasilan yang disepakati (PASSED, FAILED, BLOCKED, atau ERROR).
_Avoid_: Test status, result, outcome

**Laporan Pengujian**:
Dokumen terstruktur individual yang merangkum hasil evaluasi satu Eksekusi Kasus Uji beserta bukti visual dan langkah reproduksi.
_Avoid_: Summary doc, bug ticket, test log

**Bukti Pengujian**:
Artefak visual berupa tangkapan layar dan rekaman penjalanan peramban yang mendokumentasikan jalannya Eksekusi Kasus Uji.
_Avoid_: Evidence file, attachment, visual artifact

**Data Uji Sintetis**:
Data tiruan yang dibuat khusus untuk pengujian tanpa memuat data medis atau identitas pasien riil.
_Avoid_: Mock data, dummy data, test fixture

**Permintaan Eksekusi**:
Perintah penjalanan satu atau lebih Kasus Uji yang dikirimkan oleh sistem eksternal atau operator manusia ke sistem otomasi.
_Avoid_: Trigger event, webhook payload, job dispatch

**Sumber Kasus Uji**:
Asal spesifikasi Kasus Uji yang divalidasi, baik berupa berkas repositori terkelola maupun blok skenario terstruktur pada sistem pelacak tiket.
_Avoid_: Ticket description, test repo, issue source

**Mode Eksekusi**:
Mekanisme pengoperasian langkah pengujian pada peramban, baik secara deterministik terstruktur maupun dipandu oleh model kecerdasan buatan.
_Avoid_: Runner strategy, test driver, AI toggle
