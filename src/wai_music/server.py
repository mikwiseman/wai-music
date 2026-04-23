"""FastMCP server entry point."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Literal

from mcp.server.fastmcp import FastMCP

from wai_music.logging_config import configure_logging
from wai_music.services import ServiceContainer, create_services
from wai_music.settings import WaiMusicSettings
from wai_music.tools import artifacts, daily, entities, playback, profile, related, search, stories


def build_server(
    services: ServiceContainer,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> FastMCP:
    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[ServiceContainer]:
        try:
            yield services
        finally:
            await services.close()

    mcp = FastMCP(
        "wai-music",
        host=host,
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        lifespan=lifespan,
    )
    search.register(mcp, services)
    entities.register(mcp, services)
    related.register(mcp, services)
    stories.register(mcp, services)
    playback.register(mcp, services)
    profile.register(mcp, services)
    daily.register(mcp, services)
    artifacts.register(mcp, services)

    return mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wai-music")
    parser.add_argument("--http", action="store_true", help="Run with streamable HTTP transport")
    parser.add_argument("--port", type=int, default=8765, help="Port for HTTP transport")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging()
    services = create_services(WaiMusicSettings())
    mcp = build_server(services, port=args.port)
    transport: Literal["stdio", "streamable-http"] = "streamable-http" if args.http else "stdio"
    try:
        mcp.run(transport=transport)
    except KeyboardInterrupt:
        return 0
    finally:
        asyncio.run(services.close())
    return 0
