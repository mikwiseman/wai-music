from __future__ import annotations

from types import SimpleNamespace

from mcp.server.fastmcp import FastMCP

from wai_music.server import build_parser, build_server


def test_server_parser_and_builder() -> None:
    args = build_parser().parse_args(["--http", "--port", "9999"])
    services = SimpleNamespace(close=lambda: None)

    server = build_server(services, port=args.port)

    assert args.http is True
    assert args.port == 9999
    assert isinstance(server, FastMCP)
