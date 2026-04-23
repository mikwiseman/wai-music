from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

from wai_music.auth.oauth import WaiAccessToken
from wai_music.backends.base import BackendRegistry, SavedTracksPage
from wai_music.cache import SQLiteCache
from wai_music.models import Entity, EntityType, PlaylistRef, RelationRef, TrackMatch
from wai_music.tools.artifacts import save_markdown_notes
from wai_music.tools.daily import composition_pick
from wai_music.tools.playback import create_backend_playlist
from wai_music.tools.profile import build_profile
from wai_music.tools.related import get_related_entities
from wai_music.tools.search import search_entities


class FakeAggregator:
    async def search_entities(self, query: str, entity_type=None, limit: int = 5):
        return [Entity(type=EntityType.ARTIST, name=query, mbid="artist-1")]

    async def get_related(self, mbid: str, entity_type: EntityType, kind: str | None = None):
        return [
            RelationRef(
                kind=entity_type.value,
                target_name="Kind of Blue",
                target_mbid=mbid,
            )
        ]

    async def aggregate_entity(self, mbid: str, entity_type: EntityType, *, language: str = "en"):
        return Entity(type=entity_type, name="Resolved Daily Pick", mbid=mbid, summary=language)

    async def build_scene_story(self, scene_key: str, *, language: str = "en"):
        return SimpleNamespace(
            entity_ref=Entity(
                type=EntityType.SCENE,
                name=scene_key,
                summary=language,
            )
        )


class FakeMusicBrainz:
    async def probe(self, mbid: str):
        return EntityType.RELEASE, {"id": mbid}


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
        return SavedTracksPage(
            items=[
                TrackMatch(
                    backend="spotify",
                    track_id="saved-1",
                    name="So What",
                    artist_names=["Miles Davis"],
                )
            ],
            total=42,
        )


@pytest.mark.asyncio
async def test_search_profile_and_playlist_helpers(settings, tmp_db_path) -> None:
    registry = BackendRegistry()
    registry.register(FakeBackend())
    services = SimpleNamespace(
        aggregator=FakeAggregator(),
        backends=registry,
        cache=SQLiteCache(tmp_db_path),
        musicbrainz=FakeMusicBrainz(),
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
    assert profile.saved_count == 42
    assert profile.inferred_genres == ["jazz"]
    assert playlist.added_track_ids == ["spotify:track:1"]


def test_save_notes_writes_front_matter(settings, tmp_db_path) -> None:
    services = SimpleNamespace(
        settings=settings,
        cache=SQLiteCache(tmp_db_path),
        aggregator=FakeAggregator(),
    )
    settings.ensure_runtime_dirs()
    saved = save_markdown_notes(
        "kind-of-blue",
        "# Notes\n\nEssential listening.",
        services=services,
        entities=[Entity(type=EntityType.RELEASE, name='Kind "of" Blue', mbid="release-1")],
    )

    content = settings.playlists_dir.joinpath(
        f"{date.today().isoformat()}-kind-of-blue.md"
    ).read_text(encoding="utf-8")

    assert saved.slug == "kind-of-blue"
    assert "slug: kind-of-blue" in content
    assert 'name: "Kind \\"of\\" Blue"' in content

    with pytest.raises(FileExistsError, match="notes already exist"):
        save_markdown_notes(
            "kind-of-blue",
            "# Notes\n\nEssential listening.",
            services=services,
        )


def test_save_notes_and_playlist_history_are_user_scoped(settings, tmp_db_path) -> None:
    services = SimpleNamespace(
        settings=settings,
        cache=SQLiteCache(tmp_db_path),
        aggregator=FakeAggregator(),
    )
    settings.ensure_runtime_dirs()
    token = auth_context_var.set(
        AuthenticatedUser(
            WaiAccessToken(
                token="access-1",
                client_id="client-1",
                scopes=["mcp:tools"],
                user_id="user-1",
            )
        )
    )
    try:
        saved = save_markdown_notes(
            "private-notes",
            "# Notes\n\nUser scoped.",
            services=services,
        )
    finally:
        auth_context_var.reset(token)

    assert saved.path.endswith(f"{date.today().isoformat()}-private-notes.md")
    assert "/user-1/" in saved.path


@pytest.mark.asyncio
async def test_playlist_history_is_user_scoped(settings, tmp_db_path) -> None:
    registry = BackendRegistry()
    registry.register(FakeBackend())
    services = SimpleNamespace(
        aggregator=FakeAggregator(),
        backends=registry,
        cache=SQLiteCache(tmp_db_path),
        musicbrainz=FakeMusicBrainz(),
        settings=settings,
    )

    token = auth_context_var.set(
        AuthenticatedUser(
            WaiAccessToken(
                token="access-1",
                client_id="client-1",
                scopes=["mcp:tools"],
                user_id="user-1",
            )
        )
    )
    try:
        await create_backend_playlist(
            "spotify",
            "Scoped Playlist",
            "desc",
            ["spotify:track:1"],
            services=services,
        )
    finally:
        auth_context_var.reset(token)

    rows = services.cache.list_playlists(user_id="user-1")
    assert len(rows) == 1
    assert rows[0]["slug"] == "Scoped Playlist"


@pytest.mark.asyncio
async def test_daily_picker_modes_are_valid(settings, tmp_db_path) -> None:
    services = SimpleNamespace(
        aggregator=FakeAggregator(),
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
            language="ru",
        )
        for day, mode in enumerate(modes, start=1)
    ]
    week = [
        await composition_pick(
            services=services,
            date=f"2026-04-{day:02d}",
            language="ru",
        )
        for day in range(1, 8)
    ]

    assert [pick.mode for pick in picks] == modes
    assert len({pick.entity.name for pick in week}) >= 2
    assert picks[0].entity.summary == "ru"
    assert picks[0].suggested_actions[0].startswith("Открой")


@pytest.mark.asyncio
async def test_related_tool_uses_probed_entity_type(settings, tmp_db_path) -> None:
    services = SimpleNamespace(
        aggregator=FakeAggregator(),
        musicbrainz=FakeMusicBrainz(),
        cache=SQLiteCache(tmp_db_path),
        settings=settings,
    )

    related = await get_related_entities("release-1", services=services)

    assert related[0].kind == "release"


@pytest.mark.asyncio
async def test_playlist_creation_surfaces_local_history_failure(settings) -> None:
    registry = BackendRegistry()
    registry.register(FakeBackend())

    class BrokenCache:
        def record_playlist(self, *, backend: str, playlist_id: str, slug: str) -> None:
            raise OSError("disk full")

    services = SimpleNamespace(
        backends=registry,
        cache=BrokenCache(),
        settings=settings,
    )

    with pytest.raises(RuntimeError, match="created remotely"):
        await create_backend_playlist(
            "spotify",
            "Broken Playlist",
            "desc",
            ["spotify:track:1"],
            services=services,
        )
