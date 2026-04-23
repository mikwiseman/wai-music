"""Spotify playback backend."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from typing import Any

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from wai_music.backends.base import SavedTracksPage
from wai_music.models import PlaylistRef, TrackDetails, TrackMatch, TrackQuery
from wai_music.settings import WaiMusicSettings

COMPILATION_PATTERN = re.compile(
    r"(relaxing|best of|classical moods|study music|sleep|focus|meditation)",
    re.IGNORECASE,
)
CLASSICAL_TOKENS = ("concerto", "symphony", "sonata", "suite", "adagio", "opus", "op.")


class SpotifyBackend:
    name = "spotify"

    def __init__(self, settings: WaiMusicSettings) -> None:
        self._settings = settings
        self._client: spotipy.Spotify | None = None

    async def close(self) -> None:
        if self._client is None:
            return
        session = getattr(self._client, "_session", None)
        if session is not None:
            await asyncio.to_thread(session.close)
        self._client = None

    async def search_track(self, query: TrackQuery) -> list[TrackMatch]:
        search_query = _query_to_text(query)
        items = await self._search_tracks(search_query)
        classical = _looks_classical(search_query, query)
        filtered = [item for item in items if _allow_track_item(item, classical)]
        return [_track_match_from_item(item) for item in filtered]

    async def get_track(self, track_id: str) -> TrackDetails:
        item = await self._call("track", track_id)
        return _track_details_from_item(item)

    async def create_playlist(
        self,
        *,
        name: str,
        description: str,
        public: bool = False,
    ) -> PlaylistRef:
        current_user = await self._call("current_user")
        playlist = await self._call(
            "user_playlist_create",
            current_user["id"],
            name,
            public=public,
            description=description,
        )
        return PlaylistRef(
            backend=self.name,
            playlist_id=playlist["id"],
            name=playlist.get("name"),
            url=_external_url(playlist),
        )

    async def add_tracks(self, *, playlist_id: str, track_ids: Iterable[str]) -> list[str]:
        uris = [
            track_id if track_id.startswith("spotify:") else f"spotify:track:{track_id}"
            for track_id in track_ids
        ]
        if uris:
            await self._call("playlist_add_items", playlist_id, uris)
        return list(track_ids)

    async def get_user_top(self, *, time_range: str = "medium_term") -> dict[str, Any]:
        top_artists = await self._call("current_user_top_artists", limit=20, time_range=time_range)
        top_tracks = await self._call("current_user_top_tracks", limit=20, time_range=time_range)
        return {"artists": top_artists.get("items", []), "tracks": top_tracks.get("items", [])}

    async def get_saved(self, *, limit: int = 50) -> SavedTracksPage:
        payload = await self._call("current_user_saved_tracks", limit=limit)
        items = payload.get("items", [])
        saved: list[TrackMatch] = []
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("track"), dict):
                saved.append(_track_match_from_item(item["track"]))
        total = payload.get("total")
        return SavedTracksPage(
            items=saved,
            total=total if isinstance(total, int) else len(saved),
        )

    async def _search_tracks(self, query: str) -> list[dict[str, Any]]:
        payload = await self._call("search", q=query, type="track", limit=10)
        tracks = payload.get("tracks", {}).get("items", [])
        return [item for item in tracks if isinstance(item, dict)]

    async def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        client = self._get_client()
        method = getattr(client, method_name)
        return await asyncio.to_thread(method, *args, **kwargs)

    def _get_client(self) -> spotipy.Spotify:
        if self._client is None:
            if not self._settings.spotify_client_id or not self._settings.spotify_client_secret:
                raise RuntimeError("Spotify credentials are not configured")
            if not self._settings.spotify_cache_path.exists():
                raise RuntimeError(
                    f"Spotify token cache is missing at {self._settings.spotify_cache_path}. "
                    "Run scripts/authorize_spotify.py first."
                )
            auth_manager = SpotifyOAuth(
                client_id=self._settings.spotify_client_id,
                client_secret=self._settings.spotify_client_secret,
                redirect_uri=self._settings.spotify_redirect_uri,
                scope=" ".join(self._settings.spotify_scopes),
                cache_path=str(self._settings.spotify_cache_path),
                open_browser=False,
            )
            if auth_manager.validate_token(auth_manager.cache_handler.get_cached_token()) is None:
                raise RuntimeError(
                    f"Spotify token cache at {self._settings.spotify_cache_path} is missing, "
                    "expired, or invalid. Re-authorize with scripts/authorize_spotify.py."
                )
            self._client = spotipy.Spotify(auth_manager=auth_manager)
        return self._client


def _query_to_text(query: TrackQuery) -> str:
    if query.query:
        return query.query
    if query.entity is not None:
        return query.entity.name
    parts = [part for part in (query.artist, query.title, query.album) if part]
    return " ".join(parts)


def _looks_classical(query_text: str, query: TrackQuery) -> bool:
    haystack = f"{query_text} {query.entity.name if query.entity else ''}".lower()
    return any(token in haystack for token in CLASSICAL_TOKENS)


def _allow_track_item(item: dict[str, Any], classical: bool) -> bool:
    if not classical:
        return True
    raw_album = item.get("album")
    album = raw_album if isinstance(raw_album, dict) else {}
    album_name = album.get("name")
    if isinstance(album_name, str) and COMPILATION_PATTERN.search(album_name):
        return False
    duration_ms = item.get("duration_ms")
    if isinstance(duration_ms, int) and duration_ms < 90_000:
        return False
    return True


def _track_match_from_item(item: dict[str, Any]) -> TrackMatch:
    raw_external_ids = item.get("external_ids")
    external_ids = raw_external_ids if isinstance(raw_external_ids, dict) else {}
    raw_album = item.get("album")
    album = raw_album if isinstance(raw_album, dict) else {}
    return TrackMatch(
        backend="spotify",
        track_id=str(item["id"]),
        uri=item.get("uri"),
        url=_external_url(item),
        name=str(item["name"]),
        artist_names=[
            artist["name"]
            for artist in item.get("artists", [])
            if isinstance(artist, dict) and isinstance(artist.get("name"), str)
        ],
        album_name=album.get("name") if isinstance(album.get("name"), str) else None,
        duration_ms=item.get("duration_ms") if isinstance(item.get("duration_ms"), int) else None,
        popularity=item.get("popularity") if isinstance(item.get("popularity"), int) else None,
        external_ids={key: value for key, value in external_ids.items() if isinstance(value, str)},
    )


def _track_details_from_item(item: dict[str, Any]) -> TrackDetails:
    track = _track_match_from_item(item)
    raw_album = item.get("album")
    album = raw_album if isinstance(raw_album, dict) else {}
    return TrackDetails(
        **track.model_dump(),
        explicit=item.get("explicit") if isinstance(item.get("explicit"), bool) else None,
        preview_url=item.get("preview_url") if isinstance(item.get("preview_url"), str) else None,
        release_date=album.get("release_date")
        if isinstance(album.get("release_date"), str)
        else None,
    )


def _external_url(item: dict[str, Any]) -> str | None:
    external_urls = item.get("external_urls")
    if isinstance(external_urls, dict):
        spotify_url = external_urls.get("spotify")
        if isinstance(spotify_url, str):
            return spotify_url
    return None
