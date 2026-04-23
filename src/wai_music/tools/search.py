"""Search and resolve tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from wai_music.models import Entity, EntityType
from wai_music.services import ServiceContainer


async def search_entities(
    query: str,
    *,
    services: ServiceContainer,
    entity_type: str | None = None,
    limit: int = 5,
) -> list[Entity]:
    normalized_type = EntityType(entity_type) if entity_type is not None else None
    return await services.aggregator.search_entities(query, normalized_type, limit=limit)


async def resolve_identifier(
    identifier: str,
    *,
    services: ServiceContainer,
    language: str | None = None,
) -> Entity:
    return await services.aggregator.resolve_identifier(
        identifier,
        language=language or services.settings.default_language,
    )


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool()
    async def search(query: str, type: str | None = None, limit: int = 5) -> list[Entity]:
        """Search artists, releases, recordings, or works via MusicBrainz."""

        return await search_entities(query, services=services, entity_type=type, limit=limit)

    @mcp.tool()
    async def resolve(identifier: str, language: str | None = None) -> Entity:
        """Resolve a MusicBrainz MBID or external URL/identifier into a canonical entity."""

        return await resolve_identifier(identifier, services=services, language=language)
