"""Story tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from wai_music.models import EntityType, Fact, Story
from wai_music.services import ServiceContainer
from wai_music.tools.annotations import READ_ONLY_TOOL


async def build_story(
    mbid: str,
    *,
    entity_type: EntityType,
    services: ServiceContainer,
    language: str | None = None,
) -> Story:
    return await services.aggregator.build_story(
        mbid,
        entity_type,
        language=language or services.settings.default_language,
    )


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool(annotations=READ_ONLY_TOOL)
    async def get_artist_story(
        mbid: str,
        angle: str | None = None,
        language: str | None = None,
    ) -> Story:
        """Return a hybrid artist story with structured facts and raw Wikipedia extract."""

        story = await build_story(
            mbid, entity_type=EntityType.ARTIST, services=services, language=language
        )
        if angle:
            story.facts.insert(
                0,
                Fact(
                    kind="relation", label="Requested angle", data={"value": angle}, source="user"
                ),
            )
        return story

    @mcp.tool(annotations=READ_ONLY_TOOL)
    async def get_release_story(mbid: str, language: str | None = None) -> Story:
        """Return a hybrid release story with structured facts and raw Wikipedia extract."""

        return await build_story(
            mbid, entity_type=EntityType.RELEASE, services=services, language=language
        )

    @mcp.tool(annotations=READ_ONLY_TOOL)
    async def get_recording_story(mbid: str, language: str | None = None) -> Story:
        """Return a hybrid recording story with structured facts and raw Wikipedia extract."""

        return await build_story(
            mbid, entity_type=EntityType.RECORDING, services=services, language=language
        )

    @mcp.tool(annotations=READ_ONLY_TOOL)
    async def get_scene_story(scene_key: str, language: str | None = None) -> Story:
        """Return a hybrid scene story using curated data and Wikipedia context."""

        return await services.aggregator.build_scene_story(
            scene_key,
            language=language or services.settings.default_language,
        )
