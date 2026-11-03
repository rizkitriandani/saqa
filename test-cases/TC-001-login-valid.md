# TC-001: Valid Staff Authentication

- **ID**: TC-001
- **Title**: Login dengan username & password yang valid
- **Type**: Positive
- **Execution Mode**: deterministic
- **Target URL**: ${DEV_BASE_URL}
- **Account**: ${QA_USERNAME}

## Preconditions
- Peramban telah mengakses halaman login target

## Test Data
- username: ${QA_USERNAME}
- password: ${QA_PASSWORD}

## Test Steps
| Step | Action   | Target Element / Label   | Input Value      | Expected Step Outcome                       |
| :--- | :------- | :----------------------- | :--------------- | :------------------------------------------ |
| 1    | navigate | ${DEV_BASE_URL}          | -                | Halaman login BCA Life berhasil termuat     |
| 2    | fill     | Username or Email        | ${QA_USERNAME}   | Kolom username terisi                       |
| 3    | fill     | Password                 | ${QA_PASSWORD}   | Kolom password terisi (karakter terlindungi)|
| 4    | click    | Sign In                  | -                | Permintaan login diproses                   |

## Expected Results
- Pengguna berhasil masuk dan dialihkan dari URL `/login` menuju dashboard utama
- Judul halaman atau header menampilkan "Dashboard"
- Menampilkan identitas akun terautentikasi (label "Super User")
- Menampilkan modul Managed Care (Care Monitor, Manage Plan Benefit, Total Member, Total Claim)
