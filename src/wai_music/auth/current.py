"""Helpers for extracting the current authenticated MCP user."""

from __future__ import annotations

from mcp.server.auth.middleware.auth_context import get_access_token


def current_user_id() -> str | None:
    token = get_access_token()
    if token is None:
        return None
    user_id = getattr(token, "user_id", None)
    return user_id if isinstance(user_id, str) else None
