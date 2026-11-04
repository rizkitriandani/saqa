"""Tool handlers for Hermes Agent integration with SAQA."""

import os
import sys
import json
from pathlib import Path

# Ensure SAQA root is on sys.path
saqa_root = Path(__file__).resolve().parent.parent.parent
if str(saqa_root) not in sys.path:
    sys.path.insert(0, str(saqa_root))

from runner.engine import run_test_case
from runner.parser import compute_canonical_content_hash, parse_markdown_test_case, validate_test_case_contract
from runner.diagnostics import get_failure_context, attach_ai_diagnosis
from cli import cmd_jira_inspect, cmd_jira_process
import argparse

def _resolve_project_root(args: dict) -> Path:
    custom_root = args.get("project_root")
    if custom_root:
        return Path(custom_root).resolve()
    return Path.cwd().resolve()

def saqa_run(args: dict, **kwargs) -> str:
    """Execute a test case deterministically via Playwright."""
    try:
        test_case = args.get("test_case", "").strip()
        if not test_case:
            return json.dumps({"ok": False, "error": "Parameter 'test_case' is required."})

        project_root = _resolve_project_root(args)
        meta = run_test_case(test_case, project_root=project_root)

        return json.dumps({
            "ok": meta.get("verdict") == "PASSED",
            "run_id": meta.get("run_id"),
            "verdict": meta.get("verdict"),
            "test_case_id": meta.get("test_case_id"),
            "title": meta.get("title"),
            "duration_seconds": meta.get("execution_duration_seconds"),
            "actual_result": meta.get("actual_result", meta.get("error_message")),
            "artifacts": meta.get("artifacts", {})
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

def saqa_approve(args: dict, **kwargs) -> str:
    """Approve a test case by calculating its canonical SHA-256 hash."""
    try:
        test_case = args.get("test_case", "").strip()
        if not test_case:
            return json.dumps({"ok": False, "error": "Parameter 'test_case' is required."})

        project_root = _resolve_project_root(args)
        tc_path = project_root / test_case if not os.path.isabs(test_case) else Path(test_case)

        if not tc_path.exists():
            return json.dumps({"ok": False, "error": f"Test case file not found: {tc_path}"})

        content = tc_path.read_text(encoding="utf-8")
        parsed = parse_markdown_test_case(tc_path)
        errors = validate_test_case_contract(parsed)
        if errors:
            return json.dumps({
                "ok": False,
                "error": "Contract validation failed",
                "validation_errors": errors
            })

        canonical_hash = compute_canonical_content_hash(content)

        lines = content.splitlines()
        new_lines = []
        status_updated = False
        hash_updated = False

        for line in lines:
            if line.strip().startswith("- **Approval Status**:"):
                new_lines.append("- **Approval Status**: approved")
                status_updated = True
            elif line.strip().startswith("- **Approval Hash**:"):
                new_lines.append(f"- **Approval Hash**: {canonical_hash}")
                hash_updated = True
            else:
                new_lines.append(line)

        if not status_updated or not hash_updated:
            final_lines = []
            for line in new_lines:
                final_lines.append(line)
                if line.strip().startswith("- **Execution Mode**:") or line.strip().startswith("- **Type**:"):
                    if not status_updated:
                        final_lines.append("- **Approval Status**: approved")
                        status_updated = True
                    if not hash_updated:
                        final_lines.append(f"- **Approval Hash**: {canonical_hash}")
                        hash_updated = True
            new_lines = final_lines

        tc_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        return json.dumps({
            "ok": True,
            "test_case_id": parsed.get("id"),
            "file": str(tc_path.relative_to(project_root) if tc_path.is_relative_to(project_root) else tc_path),
            "approval_hash": canonical_hash
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

def saqa_diagnose(args: dict, **kwargs) -> str:
    """Retrieve failure context or attach AI root-cause analysis."""
    try:
        run_id = args.get("run_id", "").strip()
        if not run_id:
            return json.dumps({"ok": False, "error": "Parameter 'run_id' is required."})

        project_root = _resolve_project_root(args)
        attach_text = args.get("attach_analysis")

        if attach_text:
            res = attach_ai_diagnosis(run_id, attach_text, project_root=project_root)
            return json.dumps({
                "ok": True,
                "run_id": run_id,
                "attached": True,
                "report_docx": res.get("report_docx")
            })
        else:
            ctx = get_failure_context(run_id, project_root=project_root)
            return json.dumps({"ok": True, "context": ctx})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

def saqa_jira_inspect(args: dict, **kwargs) -> str:
    """Inspect a Jira Cloud ticket in read-only mode."""
    try:
        issue_key = args.get("issue_key", "").strip()
        if not issue_key:
            return json.dumps({"ok": False, "error": "Parameter 'issue_key' is required."})

        project_root = _resolve_project_root(args)
        cmd_args = argparse.Namespace(issue_key=issue_key, project_root=str(project_root))

        # Capture output or call directly
        ret = cmd_jira_inspect(cmd_args)
        return json.dumps({"ok": ret == 0, "issue_key": issue_key})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

def saqa_jira_process(args: dict, **kwargs) -> str:
    """Run referenced test cases on a Jira ticket and upload attachments."""
    try:
        issue_key = args.get("issue_key", "").strip()
        if not issue_key:
            return json.dumps({"ok": False, "error": "Parameter 'issue_key' is required."})

        project_root = _resolve_project_root(args)
        no_publish = bool(args.get("no_publish", False))
        cmd_args = argparse.Namespace(issue_key=issue_key, project_root=str(project_root), no_publish=no_publish)

        ret = cmd_jira_process(cmd_args)
        return json.dumps({"ok": ret == 0, "issue_key": issue_key})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

def saqa_jira_validate(args: dict, **kwargs) -> str:
    """Evaluate whether a Jira ticket is ready for automated execution."""
    try:
        issue_key = args.get("issue_key", "").strip()
        if not issue_key:
            return json.dumps({"ok": False, "error": "Parameter 'issue_key' is required."})

        project_root = _resolve_project_root(args)
        cmd_args = argparse.Namespace(issue_key=issue_key, project_root=str(project_root))

        from cli import cmd_jira_validate
        ret = cmd_jira_validate(cmd_args)
        return json.dumps({"ok": ret == 0, "issue_key": issue_key})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

def saqa_approve_and_run(args: dict, **kwargs) -> str:
    """Atomically approve a test case with its SHA-256 hash and immediately execute it."""
    try:
        app_res_str = saqa_approve(args, **kwargs)
        app_res = json.loads(app_res_str)
        if not app_res.get("ok"):
            return app_res_str

        run_res_str = saqa_run(args, **kwargs)
        run_res = json.loads(run_res_str)
        return json.dumps({
            "ok": run_res.get("ok"),
            "approval": app_res,
            "execution": run_res
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})

def handle_saqa_command(raw_args: str) -> str:
    """Handler for Hermes slash command: /saqa [args]."""
    parts = raw_args.strip().split()
    subcmd = parts[0] if parts else "help"
    sub_arg = parts[1] if len(parts) > 1 else ""

    if subcmd in ["help", "--help", "-h"]:
        return (
            "**SAQA Commands in Hermes:**\n"
            "- `/saqa run <test_case.md>` — Run a test case locally\n"
            "- `/saqa approve <test_case.md>` — Approve a test case with SHA-256 hash\n"
            "- `/saqa diagnose <run_id>` — Inspect failure context and screenshot\n"
            "- `/saqa jira inspect <KEY>` — Inspect a Jira ticket\n"
            "- `/saqa jira process <KEY>` — Run and publish tests for a Jira ticket\n"
        )
    elif subcmd == "run":
        return saqa_run({"test_case": sub_arg, "no_publish": True})
    elif subcmd == "approve":
        return saqa_approve({"test_case": sub_arg})
    elif subcmd == "diagnose":
        return saqa_diagnose({"run_id": sub_arg})
    elif subcmd == "jira":
        jira_action = parts[1] if len(parts) > 1 else "inspect"
        jira_key = parts[2] if len(parts) > 2 else ""
        if jira_action == "inspect":
            return saqa_jira_inspect({"issue_key": jira_key})
        elif jira_action == "process":
            return saqa_jira_process({"issue_key": jira_key})
    return json.dumps({"error": f"Unknown subcommand '{subcmd}'. Use '/saqa help' for guidance."})
