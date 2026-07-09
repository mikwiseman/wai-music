from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool

from wai_music.server import build_parser, build_server


async def _list_tool_names(server: FastMCP) -> list[str]:
    tools = await server.list_tools()
    return sorted(tool.name for tool in tools)


async def _tool_by_name(server: FastMCP, name: str) -> Tool:
    tools = await server.list_tools()
    for tool in tools:
        if tool.name == name:
            return tool
    raise AssertionError(f"tool {name!r} was not registered")


async def _list_resource_uris(server: FastMCP) -> list[str]:
    resources = await server.list_resources()
    return sorted(str(resource.uri) for resource in resources)


async def _list_prompt_names(server: FastMCP) -> list[str]:
    prompts = await server.list_prompts()
    return sorted(prompt.name for prompt in prompts)


def test_server_parser_and_builder() -> None:
    args = build_parser().parse_args(["--http", "--port", "9999"])
    services = SimpleNamespace(close=lambda: None)

    server = build_server(services, port=args.port)
    tool_names = asyncio.run(_list_tool_names(server))

    assert args.http is True
    assert args.port == 9999
    assert isinstance(server, FastMCP)
    assert len(tool_names) == 19
    assert "find_music" in tool_names
    assert "plan_music_discovery" in tool_names
    assert "health_check" not in tool_names


def test_server_registers_tool_safety_annotations() -> None:
    server = build_server(SimpleNamespace(close=lambda: None))

    search_tool = asyncio.run(_tool_by_name(server, "search"))
    find_music_tool = asyncio.run(_tool_by_name(server, "find_music"))
    plan_music_tool = asyncio.run(_tool_by_name(server, "plan_music_discovery"))
    create_playlist_tool = asyncio.run(_tool_by_name(server, "create_playlist"))
    add_tracks_tool = asyncio.run(_tool_by_name(server, "add_tracks_to_playlist"))
    save_notes_tool = asyncio.run(_tool_by_name(server, "save_notes"))

    assert search_tool.annotations is not None
    assert search_tool.annotations.readOnlyHint is True
    assert search_tool.annotations.destructiveHint is False

    assert find_music_tool.annotations is not None
    assert find_music_tool.annotations.readOnlyHint is True
    assert find_music_tool.annotations.destructiveHint is False

    assert plan_music_tool.annotations is not None
    assert plan_music_tool.annotations.readOnlyHint is True
    assert plan_music_tool.annotations.destructiveHint is False

    assert create_playlist_tool.annotations is not None
    assert create_playlist_tool.annotations.readOnlyHint is False
    assert create_playlist_tool.annotations.destructiveHint is True
    assert create_playlist_tool.annotations.openWorldHint is True

    assert add_tracks_tool.annotations is not None
    assert add_tracks_tool.annotations.readOnlyHint is False
    assert add_tracks_tool.annotations.destructiveHint is True
    assert add_tracks_tool.annotations.openWorldHint is True

    assert save_notes_tool.annotations is not None
    assert save_notes_tool.annotations.readOnlyHint is False
    assert save_notes_tool.annotations.destructiveHint is True
    assert save_notes_tool.annotations.openWorldHint is False


def test_server_registers_discovery_resource_and_prompt() -> None:
    server = build_server(SimpleNamespace(close=lambda: None))

    resource_uris = asyncio.run(_list_resource_uris(server))
    prompt_names = asyncio.run(_list_prompt_names(server))
    resource_contents = asyncio.run(server.read_resource("wai-music://catalogs/discovery"))
    prompt = asyncio.run(
        server.get_prompt(
            "music_discovery_session",
            {"seed": "Portishead", "mood": "haunting"},
        )
    )

    assert "wai-music://catalogs/discovery" in resource_uris
    assert "music_discovery_session" in prompt_names
    assert "MusicBrainz" in resource_contents[0].content
    assert "plan_music_discovery" in prompt.messages[0].content.text


def test_server_lifespan_close_can_be_deferred_to_host_app() -> None:
    close_calls = 0

    async def close() -> None:
        nonlocal close_calls
        close_calls += 1

    async def run_lifespan(close_on_shutdown: bool) -> None:
        server = build_server(
            SimpleNamespace(close=close),
            close_services_on_lifespan_shutdown=close_on_shutdown,
        )
        async with server._mcp_server.lifespan(server._mcp_server):
            pass

    asyncio.run(run_lifespan(close_on_shutdown=False))
    assert close_calls == 0

    asyncio.run(run_lifespan(close_on_shutdown=True))
    assert close_calls == 1
