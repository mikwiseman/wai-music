"""Relationship tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from wai_music.models import RelationRef
from wai_music.services import ServiceContainer
from wai_music.tools.annotations import READ_ONLY_TOOL


async def get_related_entities(
    mbid: str,
    *,
    services: ServiceContainer,
    kind: str | None = None,
) -> list[RelationRef]:
    entity_match = await services.musicbrainz.probe(mbid)
    if entity_match is None:
        raise ValueError(f"MusicBrainz entity not found for MBID {mbid}")
    entity_type, _payload = entity_match
    return await services.aggregator.get_related(mbid, entity_type, kind=kind)


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool(annotations=READ_ONLY_TOOL)
    async def get_related(mbid: str, kind: str | None = None) -> list[RelationRef]:
        """Return structural MusicBrainz relations such as collaborations and influences."""

        return await get_related_entities(mbid, services=services, kind=kind)
