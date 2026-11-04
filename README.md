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
| **Automated CI/CD Trigger** | ✅ Active | GitHub Actions runner triggered via Jira Automation (`.github/workflows/saqa-jira.yml`). |
| **Pi Coding Agent Skill** | ✅ Active | Portable `SKILL.md` and prompt template enabling `/saqa` slash commands. |
| **Hermes Agent Support** | ⏳ Roadmap | Skill directory linked; live Hermes binary execution pending local runtime setup. |
| **Google Docs External Watcher** | ⏳ Roadmap | Direct synchronization from Google Drive folders as test case source. |

---

## Prerequisites

- **Python**: 3.10 or higher.
- **Operating System**: Linux (Ubuntu/Debian tested) or macOS.
- **Google Workspace Shared Drive**: Required **only** if enabling Google Drive / Docs export. *(Google Service Accounts have a 0-byte quota on personal My Drive and require a Shared Drive).*
- **Jira Cloud Account**: Required **only** if enabling Jira ticket inspection or automatic commenting.

---

## Installation

### 1. Clone & Set Engine Root

Clone SAQA to your machine and define `SAQA_ROOT`:

```bash
git clone https://github.com/rizkitriandani/saqa.git /path/to/saqa
cd /path/to/saqa
export SAQA_ROOT="$(pwd)"
```
*(Tip: Add `export SAQA_ROOT=/path/to/saqa` to your `~/.bashrc` or `~/.zshrc`).*

### 2. Python Virtual Environment

Create and activate a virtual environment, then install runtime dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate

# Install core dependencies
pip install playwright python-docx google-api-python-client google-auth

# Install Playwright browser and Linux system dependencies
python3 -m playwright install --with-deps chromium
```

Run the offline unit test suite to verify the installation:

```bash
python3 -m unittest discover tests
```
*(All 46+ tests should pass with `OK`).*

---

## Install Skill in Pi Coding Agent

1. **Register the Skill**:
   ```bash
   mkdir -p ~/.agents/skills
   ln -s "$SAQA_ROOT/.agents/skills/saqa" ~/.agents/skills/saqa
   ```

2. **Register the Slash Command (`/saqa`)**:
   ```bash
   mkdir -p ~/.pi/agent/prompts
   ln -s "$SAQA_ROOT/prompts/saqa.md" ~/.pi/agent/prompts/saqa.md
   ```

3. **Activate in Pi**:
   Launch Pi from the shell where `.venv` is active, then reload prompt templates:
   ```text
   /reload
   ```

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

### Automated CI/CD Execution (Jira Webhook ➔ GitHub Actions)
See **[`docs/jira-automation-setup.md`](docs/jira-automation-setup.md)** for a step-by-step guide on setting up a Jira Cloud Automation Rule that triggers `.github/workflows/saqa-jira.yml` when cards move to `In Testing`.

---

## CLI Reference Summary

```bash
# Project configuration
python3 "$SAQA_ROOT/cli.py" config [--project-root <path>] [--project-id <id>] [--base-url <url>] [--gdrive]

# Approve test case (calculates SHA-256 hash)
python3 "$SAQA_ROOT/cli.py" approve <path> [--project-root <path>]

# Execute test case
python3 "$SAQA_ROOT/cli.py" run <path> [--no-publish] [--project-root <path>]

# Diagnose failed run with AI
python3 "$SAQA_ROOT/cli.py" diagnose <RUN_ID> [--attach "<analysis>"] [--project-root <path>]

# Publish artifacts to Google Drive or Jira
python3 "$SAQA_ROOT/cli.py" publish <RUN_ID> [--jira-issue <KEY>] [--force] [--project-root <path>]

# Jira ticket operations
python3 "$SAQA_ROOT/cli.py" jira inspect <ISSUE_KEY> [--project-root <path>]
python3 "$SAQA_ROOT/cli.py" jira process <ISSUE_KEY> [--no-publish] [--project-root <path>]

# View run history
python3 "$SAQA_ROOT/cli.py" list [--project-root <path>]
```

---

## Security & Known Limitations

- **Local Hash Scope**: The SHA-256 approval hash detects unintended local edits to steps and assertions. It does not authenticate reviewer identities or provide multi-user cryptographic signatures.
- **Credential Safety**: Passwords (`QA_PASSWORD`) are restricted exclusively to `fill` action values and are never written to test Markdown or URLs.
- **Idempotency & Replays**: Jira uploads track in-flight operations with atomic writes. Indeterminate errors (5xx server errors, network disconnects) enter `NEEDS_RECONCILIATION` to prevent duplicate remote attachments.
