from __future__ import annotations

import httpx
import pytest

from wai_music.cache import SQLiteCache
from wai_music.http import JsonHttpClient
from wai_music.models import EntityType
from wai_music.sources.musicbrainz import MusicBrainzSource


@pytest.mark.asyncio
async def test_musicbrainz_search_and_resolve_url_mock(settings, tmp_db_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ws/2/artist":
            return httpx.Response(
                200,
                json={"artists": [{"id": "mbid-artist", "name": "Miles Davis", "score": 100}]},
            )
        if request.url.path == "/ws/2/url":
            return httpx.Response(
                200,
                json={
                    "urls": [
                        {
                            "resource": "https://open.spotify.com/artist/abc123",
                            "relation-list": [
                                {
                                    "relations": [
                                        {
                                            "type": "streaming music",
                                            "artist": {"id": "mbid-artist", "name": "Miles Davis"},
                                        }
                                    ]
                                }
                            ],
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(
        base_url="https://musicbrainz.org/ws/2",
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": settings.musicbrainz_user_agent},
    ) as client:
        source = MusicBrainzSource(
            settings=settings,
            cache=SQLiteCache(tmp_db_path),
            client=JsonHttpClient(client=client),
        )
        results = await source.search(EntityType.ARTIST, "Miles Davis", limit=1)
        matches = await source.resolve_url("spotify:artist:abc123")

    assert results[0]["name"] == "Miles Davis"
    assert matches == [
        {
            "entity_type": "artist",
            "mbid": "mbid-artist",
            "name": "Miles Davis",
            "relation_type": "streaming music",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.vcr
async def test_musicbrainz_live_search_rachmaninoff(settings, tmp_db_path) -> None:
    source = MusicBrainzSource(settings=settings, cache=SQLiteCache(tmp_db_path))
    try:
        results = await source.search(EntityType.ARTIST, "Rachmaninoff", limit=3)
    finally:
        await source.close()

    assert any("Rach" in result.get("sort-name", "") for result in results)


@pytest.mark.asyncio
@pytest.mark.vcr
async def test_musicbrainz_live_search_miles_davis(settings, tmp_db_path) -> None:
    source = MusicBrainzSource(settings=settings, cache=SQLiteCache(tmp_db_path))
    try:
        results = await source.search(EntityType.ARTIST, "Miles Davis", limit=3)
    finally:
        await source.close()

    assert any(result["name"] == "Miles Davis" for result in results)


@pytest.mark.asyncio
@pytest.mark.vcr
async def test_musicbrainz_live_search_kraftwerk(settings, tmp_db_path) -> None:
    source = MusicBrainzSource(settings=settings, cache=SQLiteCache(tmp_db_path))
    try:
        results = await source.search(EntityType.ARTIST, "Kraftwerk", limit=3)
    finally:
        await source.close()

    assert any("Kraftwerk" in result["name"] for result in results)
