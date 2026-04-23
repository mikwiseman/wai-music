"""Story tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from wai_music.models import EntityType, Story
from wai_music.services import ServiceContainer


async def build_story(
    mbid: str,
    *,
    entity_type: EntityType,
    services: ServiceContainer,
    language: str = "en",
) -> Story:
    return await services.aggregator.build_story(mbid, entity_type, language=language)


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool()
    async def get_artist_story(mbid: str, angle: str | None = None, language: str = "en") -> Story:
        """Return a hybrid artist story with structured facts and raw Wikipedia extract."""

        _ = angle
        return await build_story(
            mbid, entity_type=EntityType.ARTIST, services=services, language=language
        )

    @mcp.tool()
    async def get_release_story(mbid: str, language: str = "en") -> Story:
        """Return a hybrid release story with structured facts and raw Wikipedia extract."""

        return await build_story(
            mbid, entity_type=EntityType.RELEASE, services=services, language=language
        )

    @mcp.tool()
    async def get_recording_story(mbid: str, language: str = "en") -> Story:
        """Return a hybrid recording story with structured facts and raw Wikipedia extract."""

        return await build_story(
            mbid, entity_type=EntityType.RECORDING, services=services, language=language
        )

    @mcp.tool()
    async def get_scene_story(scene_key: str, language: str = "en") -> Story:
        """Return a hybrid scene story using curated data and Wikipedia context."""

        return await services.aggregator.build_scene_story(scene_key, language=language)
