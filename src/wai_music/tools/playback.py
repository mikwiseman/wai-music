"""Playback tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from wai_music.auth.current import current_user_id
from wai_music.logging_config import get_logger
from wai_music.models import Entity, PlaylistCreationResult, PlaylistRef, TrackMatch, TrackQuery
from wai_music.services import ServiceContainer
from wai_music.tools.annotations import READ_ONLY_TOOL, REMOTE_WRITE_TOOL

logger = get_logger(__name__)


async def find_track(
    backend: str,
    query_or_entity: str | Entity,
    *,
    services: ServiceContainer,
) -> list[TrackMatch]:
    playback_backend = services.backends.get(backend)
    query = (
        TrackQuery(backend=backend, query=query_or_entity)
        if isinstance(query_or_entity, str)
        else TrackQuery(backend=backend, entity=query_or_entity)
    )
    return await playback_backend.search_track(query)


async def create_backend_playlist(
    backend: str,
    name: str,
    description: str,
    track_ids: list[str],
    *,
    services: ServiceContainer,
    public: bool = False,
) -> PlaylistCreationResult:
    user_id = current_user_id()
    logger.info(
        "playlist_create_started",
        backend=backend,
        user_id=user_id,
        name=name,
        public=public,
        track_count=len(track_ids),
    )
    playback_backend = services.backends.get(backend)
    playlist = await playback_backend.create_playlist(
        name=name,
        description=description,
        public=public,
    )
    try:
        added = await playback_backend.add_tracks(
            playlist_id=playlist.playlist_id, track_ids=track_ids
        )
    except Exception as exc:
        logger.exception(
            "playlist_add_tracks_failed",
            backend=backend,
            user_id=user_id,
            playlist_id=playlist.playlist_id,
            track_count=len(track_ids),
        )
        raise RuntimeError(
            f"playlist {playlist.playlist_id} was created remotely, but adding tracks failed"
        ) from exc
    try:
        services.cache.record_playlist(
            user_id=user_id,
            backend=backend,
            playlist_id=playlist.playlist_id,
            slug=name,
        )
    except Exception as exc:
        logger.exception(
            "playlist_history_persistence_failed",
            backend=backend,
            user_id=user_id,
            playlist_id=playlist.playlist_id,
            track_count=len(track_ids),
        )
        raise RuntimeError(
            "playlist was created remotely, but local playlist history persistence failed"
        ) from exc
    logger.info(
        "playlist_create_succeeded",
        backend=backend,
        user_id=user_id,
        playlist_id=playlist.playlist_id,
        playlist_url=playlist.url,
        public=public,
        added_track_count=len(added),
    )
    return PlaylistCreationResult(playlist=playlist, added_track_ids=added, public=public)


async def add_tracks(
    backend: str,
    playlist_id: str,
    track_ids: list[str],
    *,
    services: ServiceContainer,
) -> PlaylistCreationResult:
    user_id = current_user_id()
    logger.info(
        "playlist_add_started",
        backend=backend,
        user_id=user_id,
        playlist_id=playlist_id,
        track_count=len(track_ids),
    )
    playback_backend = services.backends.get(backend)
    try:
        added = await playback_backend.add_tracks(playlist_id=playlist_id, track_ids=track_ids)
    except Exception:
        logger.exception(
            "playlist_add_failed",
            backend=backend,
            user_id=user_id,
            playlist_id=playlist_id,
            track_count=len(track_ids),
        )
        raise
    logger.info(
        "playlist_add_succeeded",
        backend=backend,
        user_id=user_id,
        playlist_id=playlist_id,
        added_track_count=len(added),
    )
    return PlaylistCreationResult(
        playlist=PlaylistRef(backend=backend, playlist_id=playlist_id),
        added_track_ids=added,
    )


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool(annotations=READ_ONLY_TOOL)
    async def find_track_on(backend: str, query_or_entity: str | Entity) -> list[TrackMatch]:
        """Find a track on a playback backend from free text or a resolved entity."""

        return await find_track(backend, query_or_entity, services=services)

    @mcp.tool(annotations=REMOTE_WRITE_TOOL)
    async def create_playlist(
        backend: str,
        name: str,
        description: str,
        track_ids: list[str],
        public: bool = False,
    ) -> PlaylistCreationResult:
        """Create a playlist in the selected backend and add tracks to it."""

        return await create_backend_playlist(
            backend,
            name,
            description,
            track_ids,
            services=services,
            public=public,
        )

    @mcp.tool(annotations=REMOTE_WRITE_TOOL)
    async def add_tracks_to_playlist(
        backend: str,
        playlist_id: str,
        track_ids: list[str],
    ) -> PlaylistCreationResult:
        """Add track IDs to an existing backend playlist."""

        return await add_tracks(backend, playlist_id, track_ids, services=services)
