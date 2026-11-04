# TC-002: Login Page UI Elements Verification

- **ID**: TC-002
- **Title**: Verifikasi elemen antarmuka halaman login
- **Type**: Positive
- **Approval Hash**: 1c63c5c8b508d9f35eb8fd7693ce71fe776052b3bea7b463f9bd8f36efe2e154
- **Execution Mode**: deterministic
- **Approval Status**: approved
- **Target URL**: ${DEV_BASE_URL}
- **Account**: ${QA_USERNAME}

## Preconditions
- Peramban dapat mengakses target URL

## Test Data
- target_url: ${DEV_BASE_URL}

## Test Steps
| Step | Action   | Target Element / Label   | Input Value      | Expected Step Outcome                       |
| :--- | :------- | :----------------------- | :--------------- | :------------------------------------------ |
| 1    | navigate | ${DEV_BASE_URL}          | -                | Halaman login termuat                       |
| 2    | wait     | 1.0                      | 1.0              | Menunggu elemen stabil                      |

## Expected Results
- url contains "/login"
- heading contains "Welcome Back !"
- element "#username" is visible
- element "#password-input" is visible
- element "button[type='submit']" is visible
