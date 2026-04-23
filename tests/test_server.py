from __future__ import annotations

from types import SimpleNamespace

from mcp.server.fastmcp import FastMCP

from wai_music.server import build_parser, build_server


async def _list_tool_names(server: FastMCP) -> list[str]:
    tools = await server.list_tools()
    return sorted(tool.name for tool in tools)


def test_server_parser_and_builder() -> None:
    args = build_parser().parse_args(["--http", "--port", "9999"])
    services = SimpleNamespace(close=lambda: None)

    server = build_server(services, port=args.port)
    tool_names = __import__("asyncio").run(_list_tool_names(server))

    assert args.http is True
    assert args.port == 9999
    assert isinstance(server, FastMCP)
    assert len(tool_names) == 17
    assert "health_check" not in tool_names
