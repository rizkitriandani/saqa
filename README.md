# SAQA: AI-Assisted Browser E2E QA Automation

SAQA is a modular, vendor-neutral browser QA automation engine and AI agent skill. It bridges natural-language test scenario authoring with strict, deterministic Playwright execution, visual evidence capture, and automated Google Docs reporting.

---

## Architecture: 3-Pillar Orthogonal Design

```text
┌───────────────────────────────┐     ┌───────────────────────────────┐     ┌───────────────────────────────┐
│       1. INPUT ASPECT         │     │       2. PROCESS ASPECT       │     │       3. OUTPUT ASPECT        │
│ • CLI (Natural language / MD) │ ──► │ • Human Approval Gate (Hash)  │ ──► │ • Local Artifacts (Video, PNG)│
│ • Repo test cases (*.md)      │     │ • Playwright Engine           │     │ • Google Drive & Docs Native  │
│ • [Roadmap: Jira Webhook]     │     │ • Strict Generic Assertions   │     │ • [Roadmap: Jira Comments]    │
│ • [Roadmap: Google Docs Sync] │     │ • Fail-Closed Validation      │     │                               │
└───────────────────────────────┘     └───────────────────────────────┘     └───────────────────────────────┘
```

---

## Feature Status Matrix

| Capability | Status | Description |
| :--- | :---: | :--- |
| **CLI & Repo Input** | ✅ Active | Reads structured Markdown test cases from repositories or local files. |
| **Deterministic Playwright Runner** | ✅ Active | Chromium automation (`navigate`, `fill`, `click`, `select`, `wait`, `assert`). |
| **Visual Evidence Capture** | ✅ Active | Full WebM video recording and step-by-step PNG screenshots per run. |
| **Strict Assertion Compiler** | ✅ Active | Fail-closed validation for URL, heading, text, and element visibility. |
| **Tamper-Evident Approval Gate** | ✅ Active | Canonical SHA-256 hash enforcement; any content drift aborts execution. |
| **Private DOCX Report Generator** | ✅ Active | Compiles reports with embedded private screenshots and clickable video links. |
| **Google Drive & Docs Publisher** | ✅ Active | Uploads video and converts DOCX into native Google Docs in dedicated run folders. |
| **Multi-Project Declarative Config** | ✅ Active | Isolated project profiles via `saqa.json` with dedicated environments and outputs. |
| **Pi Coding Agent Skill & Slash Command** | ✅ Active | Portable `SKILL.md` and native `/saqa config` prompt template for Pi. |
| **Jira Webhook Trigger & Comments** | ⏳ Roadmap | Ingestion adapter for Jira boards and automatic ticket comment feedback. |
| **Google Docs Input Watcher** | ⏳ Roadmap | Reading test scenarios directly from external Google Docs files. |
| **Hermes Agent Runtime Verification** | ⏳ Roadmap | Skill directory linked; live Hermes binary execution pending local runtime setup. |

---

## Prerequisites

- **Python**: Version 3.10 or higher.
- **Node.js**: (Optional, if using Pi Coding Agent harness).
- **Google Workspace Shared Drive**: Required **only** if enabling Google Drive / Google Docs publishing (Google Service Accounts have 0-byte quotas on personal My Drive and require a Shared Drive).

---

## Step 1: Install the Core Engine

Clone the SAQA repository to your local machine or server:

```bash
git clone https://github.com/rizkitriandani/saqa.git /path/to/saqa
cd /path/to/saqa
```

Set the `SAQA_ROOT` environment variable in your shell profile (e.g., `~/.bashrc` or `~/.zshrc`):

```bash
export SAQA_ROOT=/path/to/saqa
```

Create and activate a virtual environment, then install the required Python dependencies:

```bash
python3 -m venv venv
source venv/bin/activate

# Install core runtime dependencies
pip install playwright python-docx google-api-python-client google-auth

# Install Playwright browser binaries
playwright install chromium
```

Verify the installation by running the offline test suite:

```bash
python3 -m unittest discover tests
```
*(All tests should complete with `OK`).*

---

## Step 2: Install the Skill in Pi Coding Agent

SAQA implements the [Agent Skills Specification](https://agentskills.io/specification). To enable the AI skill and the `/saqa` slash command in Pi:

1. **Install the Skill**:
   Symlink or copy the skill folder to your user-level skills directory:
   ```bash
   mkdir -p ~/.agents/skills
   ln -s "$SAQA_ROOT/.agents/skills/saqa" ~/.agents/skills/saqa
   ```

2. **Install the Slash Command Template**:
   Symlink the prompt template to enable `/saqa` commands:
   ```bash
   mkdir -p ~/.pi/agent/prompts
   ln -s "$SAQA_ROOT/prompts/saqa.md" ~/.pi/agent/prompts/saqa.md
   ```

3. **Reload Pi**:
   In your active Pi session, run:
   ```text
   /reload
   ```

---

## Step 3: Configure a Project (`/saqa config`)

SAQA allows configuring multiple projects independently. Each project stores its non-secret settings in `saqa.json` at its project root.

### Option A: Using the Pi Slash Command
Inside your project directory in Pi, type:
```text
/saqa config
```
Pi will guide you through:
1. Confirming the project ID / slug.
2. Setting the target Dev Base URL (e.g., `https://dev.example.com`).
3. Choosing whether to enable Google Drive reporting.
4. Reviewing the configuration preview before saving.

### Option B: Using the CLI
Navigate to your project root and run:
```bash
python3 "$SAQA_ROOT/cli.py" config --project-root . --project-id my-project --base-url "https://dev.example.com"
```

This creates:
- `saqa.json`: The declarative configuration file.
- `.env.example`: Template listing the required environment variables.

---

## Step 4: Environment & Secrets Setup

In your project directory, copy `.env.example` to `.env`:

```bash
cp .env.example .env
chmod 600 .env
```

Populate the required secrets:

```bash
DEV_BASE_URL=https://dev.example.com
QA_USERNAME=test_superuser
QA_PASSWORD=your_secure_password_here

# Required only if Google Drive output is enabled:
GOOGLE_DRIVE_FOLDER_ID=your_shared_drive_folder_id_here
GOOGLE_APPLICATION_CREDENTIALS=credentials/service-account.json
```

> **Security Rules**:
> - **Never** commit `.env` or `credentials/*.json` to version control. Add them to your project's `.gitignore`.
> - SAQA limits password substitution strictly to `fill` actions; passwords are prohibited in navigation URLs or plain text.

---

## Step 5: Day-to-Day QA Workflow

### 1. Authoring a Test Case
You can ask Pi in natural language:
> *"Use saqa to create a test case for verifying our patient registration form on staging."*

The agent generates a draft test case in `test-cases/TC-002-registration.md` with:
```markdown
- **Execution Mode**: deterministic
- **Approval Status**: pending
```

### 2. Review & Approval Gate
Before execution, inspect the draft. When satisfied, approve it to compute its SHA-256 canonical hash:
```bash
python3 "$SAQA_ROOT/cli.py" approve test-cases/TC-002-registration.md
```
*(If anyone edits the steps or assertions after approval, the hash will mismatch and the runner will abort execution with `BLOCKED`).*

### 3. Local Verification (`--no-publish`)
Execute the test case locally without uploading artifacts:
```bash
python3 "$SAQA_ROOT/cli.py" run test-cases/TC-002-registration.md --no-publish
```

Inspect local evidence in `artifacts/<RUN_ID>/`:
- `evidence.webm`: Full video recording.
- `report.docx`: Formatted report with embedded screenshots.
- `metadata.json`: Execution timestamps, steps, and verdict.

### 4. Publish to Google Drive & Docs
Once evidence is verified:
```bash
python3 "$SAQA_ROOT/cli.py" publish <RUN_ID>
```
The publisher will:
1. Create a dedicated run subfolder in your Shared Drive (`TC-002_RUN_<timestamp>_<uuid>`).
2. Upload the WebM video.
3. Upload the DOCX report and convert it to a native Google Doc with a direct clickable video link.

---

## CLI Reference Summary

```bash
# Initialize / configure a project
python3 "$SAQA_ROOT/cli.py" config [--project-root <path>]

# Approve a test case (calculates canonical SHA-256 hash)
python3 "$SAQA_ROOT/cli.py" approve <path_to_test_case.md> [--project-root <path>]

# Run a test case (deterministic execution)
python3 "$SAQA_ROOT/cli.py" run <path_to_test_case.md> [--no-publish] [--project-root <path>]

# Publish local artifacts to Google Drive
python3 "$SAQA_ROOT/cli.py" publish <RUN_ID> [--force] [--project-root <path>]

# List execution history for the project
python3 "$SAQA_ROOT/cli.py" list [--project-root <path>]
```

---

## Google Drive Setup Notes

If using Google Drive output:
1. Enable the **Google Drive API** in your Google Cloud Project.
2. Create a **Service Account** and download its JSON private key to `credentials/service-account.json`.
3. Open your organization's **Shared Drive** in Google Drive.
4. Add the Service Account email as a member with the **Contributor** or **Content Manager** role.
5. Set `GOOGLE_DRIVE_FOLDER_ID` in your `.env` to the ID of the folder inside that Shared Drive.

---

## License

MIT
