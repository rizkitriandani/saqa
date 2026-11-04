# SAQA: AI-Assisted Browser E2E QA Automation

SAQA is a modular, multi-project browser QA automation engine and AI agent skill. It bridges natural-language test authoring with Playwright execution, visual evidence capture (video recordings and step screenshots), AI failure diagnostics, Google Docs reporting, and Jira Cloud integration.

---

## 3-Pillar Orthogonal Architecture

SAQA separates testing responsibilities into three decoupled aspects:

```text
┌───────────────────────────────┐     ┌───────────────────────────────┐     ┌───────────────────────────────┐
│       1. INPUT ASPECT         │     │       2. PROCESS ASPECT       │     │       3. OUTPUT ASPECT        │
│ • CLI (Natural Language / MD) │ ──► │ • Human Approval Gate (Hash)  │ ──► │ • Local Artifacts (Video, PNG)│
│ • Repo Test Cases (*.md)      │     │ • Playwright Chromium Runner  │     │ • Google Drive & Docs Native  │
│ • Jira Cloud Issues (inspect) │     │ • Strict Generic Assertions   │     │ • Jira Comments & Attachments │
│ • [Roadmap: GDocs Watcher]    │     │ • Fail-Closed Preflight Checks│     │ • [Roadmap: Slack / Webhook]  │
└───────────────────────────────┘     └───────────────────────────────┘     └───────────────────────────────┘
```

---

## Feature Matrix

| Capability | Status | Description |
| :--- | :---: | :--- |
| **Playwright Runner** | ✅ Active | Deterministic browser automation (`navigate`, `fill`, `click`, `select`, `wait`, `assert`). |
| **Strict Assertion Compiler** | ✅ Active | Fail-closed validation for URL, heading, text, and element visibility. |
| **Human Approval Gate** | ✅ Active | SHA-256 canonical content hash verification; content drift blocks execution. |
| **Visual Evidence Capture** | ✅ Active | Full WebM video recording and per-step PNG screenshots for every run. |
| **Private DOCX Reports** | ✅ Active | Compiles reports with embedded private screenshots and clickable video hyperlinks. |
| **Google Drive & Docs Export** | ✅ Active | Converts DOCX to native Google Docs and uploads video to dedicated Shared Drive folders. |
| **AI Test Case Auditor** | ✅ Active | Pre-execution sanity checks on scenario logic, selectors, and assertions (`/saqa audit`). |
| **AI Failure Diagnostics** | ✅ Active | Post-execution visual screenshot analysis and root-cause explanation (`/saqa diagnose`). |
| **Multi-Project Isolation** | ✅ Active | Isolated environments, allowlists, and outputs configured per project via `saqa.json`. |
| **Jira Cloud Integration** | ✅ Active | Inspect tickets, run referenced tests, and attach DOCX/video + verdict comments (`cli.py jira`). |
| **Direct VPS Webhook Server** | ✅ Active | Lightweight HTTP receiver (`saqa webhook`) running tests directly on your VPS without GitHub. |
| **Multi-Runner Target Options**| ✅ Active | Configurable execution targets: `local` (VPS engine), `github` (Actions), or `gitlab` (CI). |
| **Automated CI/CD Trigger** | ✅ Active | GitHub Actions runner triggered via Jira Automation (`.github/workflows/saqa-jira.yml`). |
| **Pi Coding Agent Skill** | ✅ Active | Portable `SKILL.md` and prompt template enabling `/saqa` slash commands. |
| **Hermes Agent Plugin & Skill** | ✅ Active | Native toolset (`saqa_run`, `saqa_approve`, etc.) and `/saqa` slash command in Hermes. |
| **Google Docs External Watcher** | ⏳ Roadmap | Direct synchronization from Google Drive folders as test case source. |

---

## Prerequisites

- **Python**: 3.10 or higher.
- **Operating System**: Linux (Ubuntu/Debian tested) or macOS.
- **Google Workspace Shared Drive**: Required **only** if enabling Google Drive / Docs export. *(Google Service Accounts have a 0-byte quota on personal My Drive and require a Shared Drive).*
- **Jira Cloud Account**: Required **only** if enabling Jira ticket inspection or automatic commenting.

---

## Quick Installation (Zero-Friction)

You do **not** need to manually clone this repository. Choose your preferred environment:

### Option 1: Pi Coding Agent (One-Line Package Install)
Inside your terminal, install SAQA directly into Pi:
```bash
pi install git:github.com/rizkitriandani/saqa
```
*(Pi automatically downloads the package, registers the skill, and enables the `/saqa` slash command).*

### Option 2: Standalone Global CLI (pipx / pip)
Install `saqa` globally in your shell environment:
```bash
pipx install git+https://github.com/rizkitriandani/saqa.git
# or
pip install git+https://github.com/rizkitriandani/saqa.git

# Auto-register skills/plugins for all installed harnesses (Pi & Hermes) + Playwright:
saqa setup-harness --playwright
```

### Option 3: Hermes Agent (Nous Research)
```bash
hermes plugins install git:github.com/rizkitriandani/saqa
```

---

## Manual Developer Installation (From Source)

For developers contributing to SAQA:

### 1. Clone & Setup Virtual Environment
```bash
git clone https://github.com/rizkitriandani/saqa.git
cd saqa
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies and local editable package
pip install -e .
python3 -m playwright install --with-deps chromium
```

### 2. Auto-Register Harnesses
```bash
saqa setup-harness
```

Run the unit tests to verify:
```bash
python3 -m unittest discover tests
```
*(All 51+ offline tests should pass with `OK`).*

---

## Project Configuration & Onboarding

SAQA supports multiple projects independently. Each project maintains its non-secret settings in `saqa.json` at its project root.

### Option A: Via Pi Slash Command (`/saqa config`)
Inside your project directory in Pi, type:
```text
/saqa config
```
Pi will interactively ask:
1. **Project ID / slug**: (default: current directory name).
2. **Target Dev Base URL**: Staging URL to test (e.g., `https://staging.example.com`).
3. **Google Drive Export**: Enable/disable automated Google Docs publishing.

### Option B: Via CLI
From your target project directory:
```bash
python3 "$SAQA_ROOT/cli.py" config --project-root . --project-id my-project --base-url "https://staging.example.com" [--gdrive]
```

This generates:
- `saqa.json`: Non-secret configuration file.
- `.env.example`: Template listing required secrets.

---

## Environment & Secrets Setup

In your project directory, copy `.env.example` to `.env`:

```bash
cp -i .env.example .env
chmod 600 .env
```

Populate the required environment variables:

```bash
DEV_BASE_URL=https://staging.example.com/
QA_USERNAME=test_user
QA_PASSWORD=your_secure_password_here

# Required only if Google Drive output is enabled:
GOOGLE_DRIVE_FOLDER_ID=your_shared_drive_folder_id
GOOGLE_APPLICATION_CREDENTIALS=credentials/service-account.json

# Required only if Jira Cloud integration is used:
JIRA_BASE_URL=https://your-company.atlassian.net
JIRA_EMAIL=qa@your-company.com
JIRA_API_TOKEN=your_jira_api_token
```

If using Google Drive:
```bash
mkdir -p credentials
chmod 700 credentials
# Place your service-account.json inside credentials/
chmod 600 credentials/service-account.json
```

---

## Daily QA Workflow

### 1. Authoring a Test Case
Ask your AI agent in natural language:
> *"Use saqa to create a test case for user authentication on staging."*

The agent writes a draft to `test-cases/TC-001-login.md` with `Approval Status: pending`.

### 2. Pre-Execution Audit (`/saqa audit`)
Ask the AI to cross-check the test case before running:
```text
/saqa audit test-cases/TC-001-login.md
```
The AI verifies step logic, checks for ambiguous button/input targets, validates strict assertion syntax, and provides actionable suggestions.

### 3. Review & Approval Gate
When satisfied with the steps, approve the test case to seal it with its canonical SHA-256 hash:
```bash
python3 "$SAQA_ROOT/cli.py" approve test-cases/TC-001-login.md --project-root .
```
*(If any step or assertion is modified later, the hash will mismatch and the runner will abort execution with `BLOCKED`).*

### 4. Running the Test Locally
Execute the test locally without publishing:
```bash
python3 "$SAQA_ROOT/cli.py" run test-cases/TC-001-login.md --no-publish --project-root .
```

Artifacts are preserved in `artifacts/<RUN_ID>/`:
- `evidence.webm`: Full video recording.
- `report.docx`: Formatted report with embedded screenshots.
- `metadata.json`: Step logs, timestamps, and verdict.

### 5. AI Failure Diagnostics (`/saqa diagnose`)
If a test returns `FAILED` or `BLOCKED`:
```text
/saqa diagnose RUN_20261104_xxx
```
The AI inspects the failure screenshot, analyzes UI error states (e.g., locked account alerts, disabled buttons, validation hints), and attaches a root-cause explanation to the report.

### 6. Publishing Reports
Publish local artifacts to Google Drive:
```bash
python3 "$SAQA_ROOT/cli.py" publish <RUN_ID> --project-root .
```

---

## Jira Cloud Integration

### Manual Ticket Inspection & Execution
- **Inspect a Ticket (Read-Only)**:
  ```bash
  python3 "$SAQA_ROOT/cli.py" jira inspect MED-101 --project-root .
  ```
  *(Checks ticket status, summary, and extracts referenced test cases under the `Test Cases` heading).*

- **Execute & Attach to Jira**:
  ```bash
  python3 "$SAQA_ROOT/cli.py" jira process MED-101 --project-root .
  ```
  *(Runs referenced tests, uploads `report.docx` and `evidence.webm` to the ticket's attachments, and posts a verdict summary comment).*

### Automated Execution Options (Jira Webhook)

You have three runner options when Jira moves a card to `In Testing`:

#### Option 1: Direct on your VPS / Hermes Server (Recommended - No GitHub Actions)
Run SAQA's built-in lightweight webhook listener directly on your VPS:
```bash
# Start webhook listener on port 8080 (runner: local by default)
saqa webhook --port 8080 --runner local
```
Then configure Jira Automation to send a POST request directly to your VPS:
- **URL**: `http://<YOUR_VPS_IP_OR_DOMAIN>:8080/jira-webhook`
- **Method**: `POST`
- **Headers**: `X-Webhook-Secret: <your_secret>` (optional token defined in `.env`)
- **Body**: Custom JSON:
  ```json
  { "issue_key": "{{issue.key}}", "status": "{{issue.status.name}}" }
  ```
The VPS listener immediately returns `202 Accepted` and executes Playwright locally on the VPS, uploading reports and videos directly to Jira.

#### Option 2: Serverless via GitHub Actions
See **[`docs/jira-automation-setup.md`](docs/jira-automation-setup.md)** for configuring Jira Automation to trigger `.github/workflows/saqa-jira.yml` via `repository_dispatch`.

#### Option 3: GitLab CI Pipeline Triggers
Set `"runner_target": "gitlab"` in `saqa.json` or run `saqa webhook --runner gitlab` to dispatch pipeline triggers to GitLab CI.

---

## CLI Reference Summary

```bash
# Project configuration
saqa config [--project-root <path>] [--project-id <id>] [--base-url <url>] [--gdrive]

# Start VPS Webhook Receiver Server (direct Jira trigger)
saqa webhook [--host 0.0.0.0] [--port 8080] [--runner {local,github,gitlab}] [--project-root <path>]

# Approve test case (calculates SHA-256 hash)
saqa approve <path> [--project-root <path>]

# Execute test case
saqa run <path> [--no-publish] [--project-root <path>]

# Diagnose failed run with AI
saqa diagnose <RUN_ID> [--attach "<analysis>"] [--project-root <path>]

# Publish artifacts to Google Drive or Jira
saqa publish <RUN_ID> [--jira-issue <KEY>] [--force] [--project-root <path>]

# Jira ticket operations
saqa jira inspect <ISSUE_KEY> [--project-root <path>]
saqa jira process <ISSUE_KEY> [--no-publish] [--project-root <path>]

# Setup agent harnesses (Pi & Hermes)
saqa setup-harness [--target {all,pi,hermes}] [--playwright]

# View run history
saqa list [--project-root <path>]
```

---

## Security & Known Limitations

- **Local Hash Scope**: The SHA-256 approval hash detects unintended local edits to steps and assertions. It does not authenticate reviewer identities or provide multi-user cryptographic signatures.
- **Credential Safety**: Passwords (`QA_PASSWORD`) are restricted exclusively to `fill` action values and are never written to test Markdown or URLs.
- **Idempotency & Replays**: Jira uploads track in-flight operations with atomic writes. Indeterminate errors (5xx server errors, network disconnects) enter `NEEDS_RECONCILIATION` to prevent duplicate remote attachments.
