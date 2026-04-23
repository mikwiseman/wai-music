"""Playback backend abstraction."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from wai_music.models import PlaylistRef, TrackDetails, TrackMatch, TrackQuery


@runtime_checkable
class PlaybackBackend(Protocol):
    name: str

    async def search_track(self, query: TrackQuery) -> list[TrackMatch]: ...

    async def get_track(self, track_id: str) -> TrackDetails: ...

    async def create_playlist(
        self,
        *,
        name: str,
        description: str,
        public: bool = False,
    ) -> PlaylistRef: ...

    async def add_tracks(self, *, playlist_id: str, track_ids: Iterable[str]) -> list[str]: ...

    async def get_user_top(self, *, time_range: str = "medium_term") -> dict[str, Any]: ...

    async def get_saved(self, *, limit: int = 50) -> list[TrackMatch]: ...


class BackendRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, PlaybackBackend] = {}

    def register(self, backend: PlaybackBackend) -> None:
        self._backends[backend.name] = backend

    def get(self, name: str) -> PlaybackBackend:
        try:
            return self._backends[name]
        except KeyError as exc:
            raise ValueError(f"Unknown backend: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._backends))
