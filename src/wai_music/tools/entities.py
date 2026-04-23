"""Entity retrieval tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from wai_music.models import Entity, EntityType
from wai_music.services import ServiceContainer


async def get_entity(
    mbid: str,
    *,
    entity_type: EntityType,
    services: ServiceContainer,
    language: str = "en",
) -> Entity:
    return await services.aggregator.aggregate_entity(mbid, entity_type, language=language)


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool()
    async def get_artist(mbid: str, language: str = "en") -> Entity:
        """Get a canonical artist profile from MusicBrainz and Wikipedia."""

        return await get_entity(
            mbid, entity_type=EntityType.ARTIST, services=services, language=language
        )

    @mcp.tool()
    async def get_release(mbid: str, language: str = "en") -> Entity:
        """Get a canonical release profile, including tracklist where available."""

        return await get_entity(
            mbid, entity_type=EntityType.RELEASE, services=services, language=language
        )

    @mcp.tool()
    async def get_recording(mbid: str, language: str = "en") -> Entity:
        """Get a canonical recording profile and release context."""

        return await get_entity(
            mbid, entity_type=EntityType.RECORDING, services=services, language=language
        )

    @mcp.tool()
    async def get_work(mbid: str, language: str = "en") -> Entity:
        """Get a canonical work profile and known performance recordings."""

        return await get_entity(
            mbid, entity_type=EntityType.WORK, services=services, language=language
        )
