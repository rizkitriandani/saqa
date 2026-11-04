"""Schemas for Hermes Agent native tool calls."""

SAQA_RUN = {
    "name": "saqa_run",
    "description": (
        "Execute a deterministic browser test case via Playwright. "
        "Records WebM video, captures screenshots, evaluates assertions, and compiles reports. "
        "The test case must have 'Approval Status: approved' before running."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "test_case": {
                "type": "string",
                "description": "Path to the markdown test case file (e.g. 'test-cases/TC-001-login.md')",
            },
            "no_publish": {
                "type": "boolean",
                "description": "If true, runs locally without uploading to Google Drive or Jira (default: false)",
            },
            "project_root": {
                "type": "string",
                "description": "Optional custom project root directory (defaults to current working directory)",
            },
        },
        "required": ["test_case"],
    },
}

SAQA_APPROVE = {
    "name": "saqa_approve",
    "description": (
        "Approve a test case by calculating its canonical SHA-256 hash and setting "
        "'Approval Status: approved'. Must be called after human operator review."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "test_case": {
                "type": "string",
                "description": "Path to the test case file to approve (e.g. 'test-cases/TC-001.md')",
            },
            "project_root": {
                "type": "string",
                "description": "Optional project root directory",
            },
        },
        "required": ["test_case"],
    },
}

SAQA_DIAGNOSE = {
    "name": "saqa_diagnose",
    "description": (
        "Inspect a failed or blocked test run. Retrieves step logs, error messages, and "
        "the failure screenshot path for visual inspection. Can also attach AI root-cause analysis."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Execution Run ID (e.g. 'RUN_20261104_xxx')",
            },
            "attach_analysis": {
                "type": "string",
                "description": "Optional root-cause analysis text to attach to the report and Jira comment",
            },
            "project_root": {
                "type": "string",
                "description": "Optional project root directory",
            },
        },
        "required": ["run_id"],
    },
}

SAQA_JIRA_INSPECT = {
    "name": "saqa_jira_inspect",
    "description": (
        "Inspect a Jira Cloud ticket in read-only mode. "
        "Retrieves ticket summary, status, referenced test cases, and raw QA Scenario blocks."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "issue_key": {
                "type": "string",
                "description": "Jira Issue Key (e.g. 'MED-101')",
            },
            "project_root": {
                "type": "string",
                "description": "Optional project root directory",
            },
        },
        "required": ["issue_key"],
    },
}

SAQA_JIRA_PROCESS = {
    "name": "saqa_jira_process",
    "description": (
        "Process a Jira Cloud ticket: runs all referenced test cases, compiles DOCX and WebM video, "
        "and posts verdict comments with attachments back to the Jira ticket."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "issue_key": {
                "type": "string",
                "description": "Jira Issue Key (e.g. 'MED-101')",
            },
            "no_publish": {
                "type": "boolean",
                "description": "If true, skips uploading attachments and posting comments to Jira",
            },
            "project_root": {
                "type": "string",
                "description": "Optional project root directory",
            },
        },
        "required": ["issue_key"],
    },
}
