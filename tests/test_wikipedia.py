from __future__ import annotations

import httpx
import pytest

from wai_music.cache import SQLiteCache
from wai_music.http import JsonHttpClient
from wai_music.sources.wikipedia import WikipediaSource


@pytest.mark.asyncio
async def test_wikipedia_summary_and_facts_mock(settings, tmp_db_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "summary" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "title": "Miles Davis",
                    "extract": "Jazz trumpeter and composer.",
                    "content_urls": {
                        "desktop": {"page": "https://en.wikipedia.org/wiki/Miles_Davis"}
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "results": {
                    "bindings": [
                        {
                            "itemLabel": {"value": "Miles Davis"},
                            "birth": {"value": "1926-05-26T00:00:00Z"},
                            "death": {"value": "1991-09-28T00:00:00Z"},
                            "article": {"value": "https://en.wikipedia.org/wiki/Miles_Davis"},
                        }
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = WikipediaSource(
            settings=settings,
            cache=SQLiteCache(tmp_db_path),
            client=JsonHttpClient(client=client),
        )
        summary = await source.get_summary("Miles_Davis", language="en")
        facts = await source.get_wikidata_facts("Q1150", language="en")

    assert summary is not None
    assert summary["extract"] == "Jazz trumpeter and composer."
    assert facts["label"] == "Miles Davis"
    assert facts["wikipedia_title"] == "Miles_Davis"


@pytest.mark.asyncio
@pytest.mark.vcr
async def test_wikipedia_live_summary_and_facts(settings, tmp_db_path) -> None:
    source = WikipediaSource(settings=settings, cache=SQLiteCache(tmp_db_path))
    try:
        summary = await source.get_summary("Sergei_Rachmaninoff", language="en")
        facts = await source.get_wikidata_facts("Q131861", language="en")
    finally:
        await source.close()

    assert summary is not None
    assert "Rachmaninoff" in summary["title"]
    assert facts["label"] == "Sergei Rachmaninoff"
