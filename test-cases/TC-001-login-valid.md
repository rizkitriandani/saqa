# TC-001: Login dengan Username & Password yang Valid

- **ID**: TC-001
- **Judul**: Login dengan username & password yang valid
- **Tipe**: Positive
- **Target URL**: `${DEV_BASE_URL}`
- **Pra-kondisi**: Peramban telah mengakses halaman login target.

## Data Uji

- **Username**: `${QA_USERNAME}`
- **Password**: `${QA_PASSWORD}` (dimuat aman via environment variable)

## Langkah Pengujian

1. Buka URL login target `${DEV_BASE_URL}`.
2. Isi kolom "username or email" dengan parameter `${QA_USERNAME}`.
3. Isi kolom "password" dengan parameter `${QA_PASSWORD}`.
4. Klik tombol "Sign In".

## Hasil yang Diharapkan

Pengguna berhasil diautentikasi dan diarahkan ke dashboard Managed Care (terverifikasi melalui elemen judul/menu "Managed Care" pada antarmuka).
