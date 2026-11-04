# TC-001: Valid Staff Authentication

- **ID**: TC-001
- **Title**: Login dengan username & password yang valid
- **Type**: Positive
- **Approval Hash**: 0a763a0ee5addca1ed78693d26421ddaa66a8965e5b838ba48d10a595b65fe6a
- **Execution Mode**: deterministic
- **Approval Status**: approved
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
- url does not contain "/login"
- heading contains "Dashboard"
- text contains "Super User"
- text contains "Care Monitor"
- text contains "Total Member"
- text contains "Total Claim"
