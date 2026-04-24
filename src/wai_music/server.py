"""Application entry points for stdio MCP, hosted HTTP, and web UI."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Literal

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount

from wai_music.auth.oauth import WaiOAuthProvider, build_auth_settings
from wai_music.logging_config import configure_logging
from wai_music.services import ServiceContainer, create_services
from wai_music.settings import WaiMusicSettings
from wai_music.telemetry import configure_sentry
from wai_music.tools import artifacts, daily, entities, playback, profile, related, search, stories
from wai_music.web import build_web_routes


def build_server(
    services: ServiceContainer,
    *,
    settings: WaiMusicSettings | None = None,
    host: str | None = None,
    port: int | None = None,
    close_services_on_lifespan_shutdown: bool = True,
) -> FastMCP:
    configured_candidate = settings if settings is not None else getattr(services, "settings", None)
    configured = (
        configured_candidate
        if isinstance(configured_candidate, WaiMusicSettings)
        else WaiMusicSettings()
    )
    if host is not None:
        configured.host = host
    if port is not None:
        configured.port = port

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[ServiceContainer]:
        try:
            yield services
        finally:
            if close_services_on_lifespan_shutdown:
                await services.close()

    oauth_provider: WaiOAuthProvider | None = None
    auth_settings = None
    if configured.oauth_enabled:
        if configured.secret_key is None:
            raise RuntimeError("WAI_MUSIC_SECRET_KEY must be configured for hosted OAuth mode")
        oauth_provider = WaiOAuthProvider(store=services.auth_store, settings=configured)
        auth_settings = build_auth_settings(configured)

    mcp = FastMCP(
        "wai-music",
        host=configured.host,
        port=configured.port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        lifespan=lifespan,
        auth_server_provider=oauth_provider,
        auth=auth_settings,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=configured.allowed_hosts,
            allowed_origins=configured.allowed_origins,
        ),
        website_url=configured.public_base_url,
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


def build_web_app(
    services: ServiceContainer,
    *,
    settings: WaiMusicSettings | None = None,
) -> Starlette:
    configured = settings or services.settings
    mcp = build_server(
        services,
        settings=configured,
        close_services_on_lifespan_shutdown=False,
    )
    oauth_provider = (
        WaiOAuthProvider(store=services.auth_store, settings=configured)
        if configured.oauth_enabled
        else None
    )
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                await services.close()

    return Starlette(
        debug=False,
        routes=[
            *build_web_routes(services, configured, oauth_provider),
            Mount("/", app=mcp_app),
        ],
        lifespan=lifespan,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wai-music")
    parser.add_argument("--http", action="store_true", help="Run the hosted HTTP app with web UI")
    parser.add_argument("--host", default=None, help="Bind host for HTTP transport")
    parser.add_argument("--port", type=int, default=None, help="Port for HTTP transport")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging()
    settings = WaiMusicSettings()
    if args.host is not None:
        settings.host = args.host
    if args.port is not None:
        settings.port = args.port
    configure_sentry(settings)
    services = create_services(settings)
    transport: Literal["stdio", "streamable-http"] = "streamable-http" if args.http else "stdio"
    if transport == "stdio":
        mcp = build_server(services, settings=settings)
        try:
            mcp.run(transport="stdio")
        except KeyboardInterrupt:
            return 0
        finally:
            asyncio.run(services.close())
        return 0

    app = build_web_app(services, settings=settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
    return 0
