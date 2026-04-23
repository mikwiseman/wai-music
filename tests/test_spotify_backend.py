from __future__ import annotations

import pytest

from wai_music.backends.spotify import SpotifyBackend, _allow_track_item, _looks_classical
from wai_music.models import PlaylistRef, TrackQuery
from wai_music.settings import WaiMusicSettings


def test_classical_heuristics_filter_compilations() -> None:
    query = TrackQuery(query="Piano Concerto no. 2 adagio")
    assert _looks_classical(query.query or "", query) is True

    compilation = {
        "album": {"name": "Relaxing Classical Moods"},
        "duration_ms": 300000,
    }
    short_track = {
        "album": {"name": "Rachmaninoff Concerto"},
        "duration_ms": 60000,
    }
    valid = {
        "album": {"name": "Rachmaninoff: Piano Concertos"},
        "duration_ms": 600000,
    }

    assert _allow_track_item(compilation, classical=True) is False
    assert _allow_track_item(short_track, classical=True) is False
    assert _allow_track_item(valid, classical=True) is True


@pytest.mark.asyncio
async def test_create_playlist_uses_current_user_playlist_create(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("SPOTIFY_CACHE_PATH", str(tmp_path / "spotify.json"))
    settings = WaiMusicSettings()

    class StubBackend(SpotifyBackend):
        def __init__(self, settings: WaiMusicSettings) -> None:
            super().__init__(settings)
            self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

        async def _call(self, method_name: str, *args: object, **kwargs: object) -> object:
            self.calls.append((method_name, args, kwargs))
            if method_name == "current_user_playlist_create":
                return {
                    "id": "playlist-1",
                    "name": "Test Playlist",
                    "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist-1"},
                }
            raise AssertionError(f"unexpected method: {method_name}")

    backend = StubBackend(settings)

    playlist = await backend.create_playlist(
        name="Test Playlist",
        description="desc",
        public=False,
    )

    assert playlist == PlaylistRef(
        backend="spotify",
        playlist_id="playlist-1",
        name="Test Playlist",
        url="https://open.spotify.com/playlist/playlist-1",
    )
    assert backend.calls == [
        (
            "current_user_playlist_create",
            ("Test Playlist",),
            {"public": False, "description": "desc"},
        )
    ]
