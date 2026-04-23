"""Listening profile tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from wai_music.backends.base import SavedTracksPage
from wai_music.models import Entity, EntityType, ExternalIds, ListeningProfile, TrackMatch
from wai_music.services import ServiceContainer


def _infer_eras(track_names: list[TrackMatch]) -> list[str]:
    eras: set[str] = set()
    for track in track_names:
        album_name = track.album_name or ""
        lowered = album_name.lower()
        if any(token in lowered for token in ("bebop", "cool", "blue")):
            eras.add("mid-century")
        if any(token in lowered for token in ("future", "computer", "digital")):
            eras.add("late-modern")
    return sorted(eras)


def _infer_genres(artist_names: list[str]) -> list[str]:
    genres: set[str] = set()
    for artist in artist_names:
        lowered = artist.lower()
        if lowered in {"miles davis", "john coltrane"}:
            genres.add("jazz")
        if lowered in {"kraftwerk", "aphex twin"}:
            genres.add("electronic")
        if lowered in {"sergei rachmaninoff", "rachmaninoff"}:
            genres.add("classical")
    return sorted(genres)


async def build_profile(
    backend: str,
    *,
    services: ServiceContainer,
    time_range: str = "medium_term",
) -> ListeningProfile:
    playback_backend = services.backends.get(backend)
    raw_top = await playback_backend.get_user_top(time_range=time_range)
    saved_tracks = await playback_backend.get_saved(limit=50)
    if not isinstance(saved_tracks, SavedTracksPage):
        raise TypeError("playback backend returned invalid saved tracks page")
    top_tracks = list(raw_top.get("tracks", []))

    normalized_top_tracks: list[TrackMatch] = []
    for item in top_tracks:
        if isinstance(item, TrackMatch):
            normalized_top_tracks.append(item)
        elif isinstance(item, dict):
            normalized_top_tracks.append(
                TrackMatch(
                    backend=backend,
                    track_id=str(item["id"]),
                    uri=item.get("uri"),
                    url=item.get("external_urls", {}).get("spotify")
                    if isinstance(item.get("external_urls"), dict)
                    else None,
                    name=str(item["name"]),
                    artist_names=[
                        artist["name"]
                        for artist in item.get("artists", [])
                        if isinstance(artist, dict) and isinstance(artist.get("name"), str)
                    ],
                    album_name=item.get("album", {}).get("name")
                    if isinstance(item.get("album"), dict)
                    else None,
                )
            )

    top_artists: list[Entity] = []
    for item in raw_top.get("artists", []):
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            top_artists.append(
                Entity(
                    type=EntityType.ARTIST,
                    name=item["name"],
                    external_ids=ExternalIds(
                        spotify=item.get("uri") if isinstance(item.get("uri"), str) else None
                    ),
                )
            )

    artist_names = [artist.name for artist in top_artists]
    return ListeningProfile(
        top_artists=top_artists,
        top_tracks=normalized_top_tracks,
        saved_count=saved_tracks.total,
        inferred_eras=_infer_eras(normalized_top_tracks),
        inferred_genres=_infer_genres(artist_names),
    )


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool()
    async def get_listening_profile(
        backend: str = "spotify",
        time_range: str = "medium_term",
    ) -> ListeningProfile:
        """Summarize a user's backend listening habits into artists, tracks, eras, and genres."""

        return await build_profile(backend, services=services, time_range=time_range)
