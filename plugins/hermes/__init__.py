"""Hermes Agent native plugin registration for SAQA."""

import logging
from . import schemas, tools

logger = logging.getLogger(__name__)

def register(ctx):
    """
    Registrasi toolset dan slash command SAQA ke dalam Hermes Agent runtime.
    Sesuai dengan spesifikasi plugin resmi Nous Research Hermes Agent.
    """
    # 1. Registrasi 5 tools utama
    ctx.register_tool(
        name="saqa_run",
        toolset="saqa",
        schema=schemas.SAQA_RUN,
        handler=tools.saqa_run
    )
    ctx.register_tool(
        name="saqa_approve",
        toolset="saqa",
        schema=schemas.SAQA_APPROVE,
        handler=tools.saqa_approve
    )
    ctx.register_tool(
        name="saqa_approve_and_run",
        toolset="saqa",
        schema=schemas.SAQA_APPROVE_AND_RUN,
        handler=tools.saqa_approve_and_run
    )
    ctx.register_tool(
        name="saqa_diagnose",
        toolset="saqa",
        schema=schemas.SAQA_DIAGNOSE,
        handler=tools.saqa_diagnose
    )
    ctx.register_tool(
        name="saqa_jira_inspect",
        toolset="saqa",
        schema=schemas.SAQA_JIRA_INSPECT,
        handler=tools.saqa_jira_inspect
    )
    ctx.register_tool(
        name="saqa_jira_validate",
        toolset="saqa",
        schema=schemas.SAQA_JIRA_VALIDATE,
        handler=tools.saqa_jira_validate
    )
    ctx.register_tool(
        name="saqa_jira_process",
        toolset="saqa",
        schema=schemas.SAQA_JIRA_PROCESS,
        handler=tools.saqa_jira_process
    )

    # 2. Registrasi in-session slash command (/saqa)
    if hasattr(ctx, "register_command"):
        ctx.register_command(
            "saqa",
            tools.handle_saqa_command,
            description="SAQA QA Automation commands: /saqa [run|approve|diagnose|jira]"
        )

    logger.info("SAQA plugin registered successfully with 5 tools and /saqa command.")
