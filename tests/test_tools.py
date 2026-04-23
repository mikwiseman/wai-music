from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from wai_music.backends.base import BackendRegistry
from wai_music.cache import SQLiteCache
from wai_music.models import Entity, EntityType, PlaylistRef, TrackMatch
from wai_music.tools.artifacts import save_markdown_notes
from wai_music.tools.daily import composition_pick
from wai_music.tools.playback import create_backend_playlist
from wai_music.tools.profile import build_profile
from wai_music.tools.search import search_entities


class FakeAggregator:
    async def search_entities(self, query: str, entity_type=None, limit: int = 5):
        return [Entity(type=EntityType.ARTIST, name=query, mbid="artist-1")]


class FakeBackend:
    name = "spotify"

    async def search_track(self, query):
        return [
            TrackMatch(
                backend="spotify",
                track_id="track-1",
                name="Blue in Green",
                artist_names=["Miles Davis"],
            )
        ]

    async def get_track(self, track_id: str):
        raise NotImplementedError

    async def create_playlist(self, *, name: str, description: str, public: bool = False):
        return PlaylistRef(backend="spotify", playlist_id="playlist-1", name=name)

    async def add_tracks(self, *, playlist_id: str, track_ids):
        return list(track_ids)

    async def get_user_top(self, *, time_range: str = "medium_term"):
        return {
            "artists": [{"name": "Miles Davis", "uri": "spotify:artist:1"}],
            "tracks": [
                {
                    "id": "track-1",
                    "name": "Blue in Green",
                    "uri": "spotify:track:1",
                    "artists": [{"name": "Miles Davis"}],
                    "album": {"name": "Kind of Blue"},
                    "external_urls": {"spotify": "https://open.spotify.com/track/1"},
                }
            ],
        }

    async def get_saved(self, *, limit: int = 50):
        return [
            TrackMatch(
                backend="spotify",
                track_id="saved-1",
                name="So What",
                artist_names=["Miles Davis"],
            )
        ]


@pytest.mark.asyncio
async def test_search_profile_and_playlist_helpers(settings, tmp_db_path) -> None:
    registry = BackendRegistry()
    registry.register(FakeBackend())
    services = SimpleNamespace(
        aggregator=FakeAggregator(),
        backends=registry,
        cache=SQLiteCache(tmp_db_path),
        settings=settings,
    )

    search_results = await search_entities("Miles Davis", services=services, limit=1)
    profile = await build_profile("spotify", services=services)
    playlist = await create_backend_playlist(
        "spotify",
        "Test Playlist",
        "desc",
        ["spotify:track:1"],
        services=services,
    )

    assert search_results[0].name == "Miles Davis"
    assert profile.saved_count == 1
    assert profile.inferred_genres == ["jazz"]
    assert playlist.added_track_ids == ["spotify:track:1"]


def test_save_notes_writes_front_matter(settings, tmp_db_path) -> None:
    services = SimpleNamespace(
        settings=settings,
        cache=SQLiteCache(tmp_db_path),
    )
    settings.ensure_runtime_dirs()
    saved = save_markdown_notes(
        "kind-of-blue",
        "# Notes\n\nEssential listening.",
        services=services,
        entities=[Entity(type=EntityType.RELEASE, name="Kind of Blue", mbid="release-1")],
    )

    content = settings.playlists_dir.joinpath(
        f"{date.today().isoformat()}-kind-of-blue.md"
    ).read_text(encoding="utf-8")

    assert saved.slug == "kind-of-blue"
    assert "slug: kind-of-blue" in content
    assert "Kind of Blue" in content


@pytest.mark.asyncio
async def test_daily_picker_modes_are_valid(settings, tmp_db_path) -> None:
    services = SimpleNamespace(
        settings=settings,
        cache=SQLiteCache(tmp_db_path),
    )
    modes = [
        "anniversary",
        "seasonal",
        "scene_dive",
        "chronological",
        "random_curated",
    ]

    picks = [
        await composition_pick(
            services=services,
            mode=mode,
            date=f"2026-04-{day:02d}",
        )
        for day, mode in enumerate(modes, start=1)
    ]
    week = [
        await composition_pick(
            services=services,
            date=f"2026-04-{day:02d}",
        )
        for day in range(1, 8)
    ]

    assert [pick.mode for pick in picks] == modes
    assert len({pick.entity.name for pick in week}) >= 2
