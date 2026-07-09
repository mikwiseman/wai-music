"""High-level MCP workflow tools and discovery resources."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from wai_music.auth.current import current_user_id
from wai_music.catalogs import (
    build_discovery_workflow_prompt,
    build_discovery_workflow_steps,
    catalog_map_json,
    list_catalog_signals,
)
from wai_music.languages import validate_language
from wai_music.models import MusicDiscoveryPlan, MusicFinderChoices
from wai_music.services import ServiceContainer
from wai_music.tools.annotations import READ_ONLY_TOOL
from wai_music.tools.finder import find_music_for_choices


async def build_music_discovery_plan(
    choices: MusicFinderChoices,
    *,
    services: ServiceContainer,
    backend: str = "spotify",
    limit: int | None = None,
    language: str | None = None,
    spotify_connected: bool | None = None,
) -> MusicDiscoveryPlan:
    """Build recommendations plus the MCP source plan used to refine them."""

    resolved_language = validate_language(
        language or choices.language,
        default=services.settings.default_language,
    )
    connection_state = (
        _current_user_has_spotify(services) if spotify_connected is None else spotify_connected
    )
    result = await find_music_for_choices(
        choices,
        services=services,
        backend=backend,
        limit=limit,
        language=resolved_language,
    )
    catalogs = list_catalog_signals(choices, spotify_connected=connection_state)
    steps = build_discovery_workflow_steps(choices, spotify_connected=connection_state)
    prompt = build_discovery_workflow_prompt(
        choices=choices,
        base_prompt=result.mcp_prompt,
        catalogs=catalogs,
        steps=steps,
    )
    return MusicDiscoveryPlan(
        choices=choices,
        result=result,
        catalogs=catalogs,
        workflow_steps=steps,
        mcp_prompt=prompt,
    )


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool(annotations=READ_ONLY_TOOL)
    async def plan_music_discovery(
        choices: MusicFinderChoices,
        backend: str = "spotify",
        limit: int | None = None,
        language: str | None = None,
    ) -> MusicDiscoveryPlan:
        """Plan a source-aware music discovery workflow and return ranked candidates."""

        return await build_music_discovery_plan(
            choices,
            services=services,
            backend=backend,
            limit=limit,
            language=language,
        )

    @mcp.resource(
        "wai-music://catalogs/discovery",
        name="wai_music_discovery_catalogs",
        title="wai-music Discovery Catalogs",
        description="Catalog capabilities, service status, limits, and MCP tool mapping.",
        mime_type="application/json",
    )
    def discovery_catalogs() -> str:
        return catalog_map_json()

    @mcp.prompt(
        name="music_discovery_session",
        title="Music Discovery Session",
        description="Start a source-aware wai-music discovery session.",
    )
    def music_discovery_session(seed: str, mood: str = "balanced") -> str:
        return "\n".join(
            [
                "Use wai-music as the music-data MCP server.",
                f"seed: {seed}",
                f"mood: {mood}",
                "First call plan_music_discovery with explicit choices.",
                "Read wai-music://catalogs/discovery if you need source limits or planned adapters.",
                "Use read-only tools before any playlist write tools.",
            ]
        )


def _current_user_has_spotify(services: ServiceContainer) -> bool:
    try:
        user_id = current_user_id()
    except LookupError:
        return False
    if user_id is None:
        return False
    return services.auth_store.get_spotify_connection(user_id) is not None
