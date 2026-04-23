"""Relationship tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from wai_music.models import EntityType, RelationRef
from wai_music.services import ServiceContainer


async def get_related_entities(
    mbid: str,
    *,
    services: ServiceContainer,
    kind: str | None = None,
) -> list[RelationRef]:
    return await services.aggregator.get_related(mbid, EntityType.ARTIST, kind=kind)


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool()
    async def get_related(mbid: str, kind: str | None = None) -> list[RelationRef]:
        """Return structural MusicBrainz relations such as collaborations and influences."""

        return await get_related_entities(mbid, services=services, kind=kind)
