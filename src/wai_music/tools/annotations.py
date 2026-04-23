"""Shared MCP tool annotation presets."""

from __future__ import annotations

from mcp.types import ToolAnnotations

READ_ONLY_TOOL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
)

LOCAL_WRITE_TOOL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)

REMOTE_WRITE_TOOL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)
