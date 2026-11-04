# SAQA: AI-Assisted Browser E2E QA Automation

SAQA is a modular browser QA automation engine and AI agent skill. It bridges natural-language test scenario authoring with Playwright execution, visual evidence capture (video and screenshots), and Google Docs reporting.

---

## What SAQA Does

1. **AI Authoring (`SKILL.md`)**: QA writes test scenarios in natural language (English or Indonesian); the agent drafts a structured test case.
2. **Human Approval Gate**: Every draft starts as `pending`. An operator inspects the draft and approves it with `cli.py approve <path>`, which signs it with a canonical SHA-256 content hash.
3. **Core Runner**: Executes approved Markdown steps (`navigate`, `fill`, `click`, `select`, `wait`, `assert`) via Playwright Chromium.
4. **Evidence & Reports**: Records WebM video per run, takes PNG screenshots, compiles a DOCX report with embedded private images, and optionally converts it to a native Google Doc in a Google Workspace Shared Drive.

---

## Current Status & Availability

- **Active & Tested**:
  - Deterministic Playwright execution from Markdown files (`test-cases/*.md`).
  - Strict generic assertions (`url contains`, `heading contains`, `text contains`, `element is visible`).
  - Local evidence generation (`artifacts/<RUN_ID>/` with video, screenshots, metadata, and DOCX).
  - Google Drive & Google Docs native publishing with embedded screenshots and clickable video links.
  - Multi-project configuration via `saqa.json` with isolated environments and outputs.
  - Pi Coding Agent skill (`.agents/skills/saqa/SKILL.md`) and prompt template (`/saqa [config|run|approve|list]`).
- **Roadmap / Not Yet Implemented**:
  - Jira webhook trigger and automatic issue comment feedback.
  - Google Docs external file watcher.
  - Autonomous AI execution mode (`Execution Mode: ai` is currently rejected fail-closed).
  - Hermes runtime binary verification (skill directory linked; binary not yet installed on this server).

---

## Prerequisites

- **Python**: 3.10 or higher.
- **Operating System**: Linux (Ubuntu/Debian tested) or macOS.
- **Google Workspace Shared Drive**: Required **only** if enabling Google Drive / Docs export. *(Google Service Accounts have a 0-byte quota on personal My Drive and require a Shared Drive to own files).*

---

## Installation

### 1. Clone & Set Engine Root

Clone the repository and set `SAQA_ROOT`:

```bash
git clone https://github.com/rizkitriandani/saqa.git /path/to/saqa
cd /path/to/saqa
export SAQA_ROOT="$(pwd)"
```
*(Add `export SAQA_ROOT=/path/to/saqa` to your `~/.bashrc` or `~/.zshrc` profile).*

### 2. Python Virtual Environment

Create and activate a virtual environment, then install runtime dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate

# Install required packages
pip install playwright python-docx google-api-python-client google-auth

# Install Playwright browser and Linux system dependencies
python3 -m playwright install --with-deps chromium
```

Verify your installation by running the test suite:

```bash
python3 -m unittest discover tests
```

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
   Launch Pi from the shell where `.venv` is active, then reload prompts:
   ```text
   /reload
   ```

---

## Configuring a Project

Each target project has its own `saqa.json` and `.env` at its project root.

### Via Pi Slash Command (`/saqa config`)
In your project directory, run:
```text
/saqa config
```
Follow the interactive prompts to define your project slug, base URL, and whether to enable Google Drive exports.

### Via CLI
Run from your target project directory:
```bash
python3 "$SAQA_ROOT/cli.py" config --project-root . --project-id my-project --base-url "https://dev.example.com" [--gdrive]
```

This creates:
- `saqa.json`: Non-secret project configuration.
- `.env.example`: Template of required environment variables.

---

## Environment & Credentials Setup

In your project directory, copy `.env.example` to `.env`:

```bash
cp -i .env.example .env
chmod 600 .env
```

Fill in your test credentials:

```bash
DEV_BASE_URL=https://dev.example.com
QA_USERNAME=test_user
QA_PASSWORD=your_password_here

# Required only if --gdrive was enabled during config:
GOOGLE_DRIVE_FOLDER_ID=your_shared_drive_folder_id
GOOGLE_APPLICATION_CREDENTIALS=credentials/service-account.json
```

If using Google Drive:
```bash
mkdir -p credentials
chmod 700 credentials
# Place your service-account.json inside credentials/
chmod 600 credentials/service-account.json
```

---

## Day-to-Day QA Workflow

### 1. Authoring a Test Case
Ask your AI agent in natural language:
> *"Use saqa to create a test case for verifying login on dev."*

The agent writes a draft to `test-cases/TC-xxx.md` with:
```markdown
- **Execution Mode**: deterministic
- **Approval Status**: pending
```
*(See `docs/test-case-contract.md` for format specifications).*

### 2. Review & Approval Gate
Review the generated steps. When ready, approve the test case to calculate its SHA-256 canonical hash:

```bash
python3 "$SAQA_ROOT/cli.py" approve test-cases/TC-xxx.md --project-root .
```

### 3. Execution & Local Verification
Run the test locally without publishing:

```bash
python3 "$SAQA_ROOT/cli.py" run test-cases/TC-xxx.md --no-publish --project-root .
```

Inspect local artifacts under `artifacts/<RUN_ID>/`:
- `evidence.webm`: Full video recording.
- `report.docx`: Formatted report with embedded screenshots.
- `metadata.json`: Step logs, timestamps, and verdict.

### 4. Publish to Google Drive & Docs
When ready to share:

```bash
python3 "$SAQA_ROOT/cli.py" publish <RUN_ID> --project-root .
```

---

## CLI Reference

```bash
# Configure project profile
python3 "$SAQA_ROOT/cli.py" config [--project-root <path>] [--project-id <id>] [--base-url <url>] [--gdrive] [--overwrite]

# Approve a test case (calculates SHA-256 canonical hash)
python3 "$SAQA_ROOT/cli.py" approve <path> [--project-root <path>]

# Run a test case
python3 "$SAQA_ROOT/cli.py" run <path> [--no-publish] [--project-root <path>]

# Publish local run artifacts to Google Drive
python3 "$SAQA_ROOT/cli.py" publish <RUN_ID> [--force] [--project-root <path>]

# List execution history for the project
python3 "$SAQA_ROOT/cli.py" list [--project-root <path>]
```

---

## Known Limitations

- **Local Hash Scope**: The SHA-256 approval hash detects unintended local edits to steps and assertions. It does not authenticate reviewer identities or provide multi-user cryptographic signatures.
- **Cross-Origin Navigation**: Preflight validation blocks navigation outside configured origins; runtime redirect defense across third-party domains is subject to ongoing hardening.
- **Sensitive Data**: Password substitution is restricted to `fill` action values, but test scenarios should always run against synthetic test accounts in staging environments.
