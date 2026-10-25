#!/usr/bin/env python3
"""One-request, opt-in OpenAI smoke test for the SP-101 task parser.

This script is deliberately not imported by FastAPI or pytest. It contacts
OpenAI only when a developer explicitly runs it with an ``OPENAI_API_KEY`` in
the current terminal environment. The key is never printed, stored, or logged.
"""

from __future__ import annotations

import asyncio
import os
import sys

from app.services.task_parser import TaskParser, configured_openai_client

SAMPLE_TASK = "Find a project-management tool for 10 people under $200/month with SSO."


async def run() -> int:
    """Make exactly one structured-output request through the existing adapter."""

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is required; no OpenAI request was made.", file=sys.stderr)
        return 2

    try:
        parser = TaskParser(configured_openai_client())
        result = await parser.parse(SAMPLE_TASK)
    except Exception:
        # Do not expose SDK internals, request headers, or environment values.
        print("OpenAI smoke test could not start safely; no details were exposed.", file=sys.stderr)
        return 1

    print("Validated structured parsed task:")
    print(result.parsed_task.model_dump_json(indent=2) if result.parsed_task else "null")
    print("Missing fields:")
    print(result.missing_fields)
    print("Clarification questions:")
    print(result.clarification_questions)
    return 0 if result.parsed_task is not None else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
