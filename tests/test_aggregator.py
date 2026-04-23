from __future__ import annotations

import pytest

from wai_music.aggregator import (
    EntityAggregator,
    _children_from_payload,
    _coalesce,
    _country,
    _extract_external_ids,
    _extract_mbid_from_identifier,
    _facts_from_entity,
    _first_str,
    _nested_get,
    _primary_date,
    _relations_from_payload,
    _title_from_wikipedia_url,
)
from wai_music.models import Entity, EntityType


class FakeMusicBrainz:
    async def search(self, entity_type, query, limit=5):
        lookup = {
            EntityType.ARTIST: [{"id": "artist-mbid", "name": "Miles Davis", "score": 98}],
            EntityType.RELEASE: [{"id": "release-mbid", "title": "Kind of Blue", "score": 96}],
            EntityType.RECORDING: [{"id": "recording-mbid", "title": "So What", "score": 97}],
            EntityType.WORK: [{"id": "work-mbid", "title": "Blue in Green", "score": 95}],
        }
        return lookup.get(entity_type, [])[:limit]

    async def probe(self, mbid: str):
        return EntityType.ARTIST, {"id": mbid}

    async def resolve_url(self, resource: str):
        return [{"entity_type": "artist", "mbid": "artist-mbid", "name": "Miles Davis"}]

    async def lookup(self, entity_type, mbid, includes=None):
        assert entity_type is EntityType.ARTIST
        return {
            "id": mbid,
            "name": "Miles Davis",
            "country": "US",
            "life-span": {"begin": "1926-05-26"},
            "relations": [
                {
                    "type": "wikidata",
                    "target-type": "url",
                    "url": {"resource": "https://www.wikidata.org/wiki/Q1150"},
                },
                {
                    "type": "member of band",
                    "target-type": "artist",
                    "artist": {"id": "other-mbid", "name": "Charlie Parker"},
                },
            ],
            "tags": [{"name": "jazz"}],
        }


class FakeWikipedia:
    async def get_wikidata_facts(self, qid: str, *, language: str = "en"):
        assert qid == "Q1150"
        return {
            "qid": qid,
            "label": "Miles Davis",
            "birth_date": "1926-05-26T00:00:00Z",
            "death_date": "1991-09-28T00:00:00Z",
            "wikipedia_title": "Miles_Davis",
        }

    async def get_summary(self, title: str, *, language: str = "en"):
        if title == "Miles_Davis":
            return {
                "extract": "American jazz trumpeter.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Miles_Davis"}},
                "thumbnail": {"source": "https://example.com/miles.jpg", "width": 100, "height": 200},
            }
        return {
            "extract": "Machine-funk futurism from Detroit.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Detroit_techno"}},
        }


@pytest.mark.asyncio
async def test_aggregator_builds_entity_and_story() -> None:
    aggregator = EntityAggregator(FakeMusicBrainz(), FakeWikipedia())

    entity = await aggregator.aggregate_entity("artist-mbid", EntityType.ARTIST, language="en")
    story = await aggregator.build_story("artist-mbid", EntityType.ARTIST, language="en")
    resolved = await aggregator.resolve_identifier("spotify:artist:abc123", language="en")
    searched = await aggregator.search_entities("Miles", limit=4)
    mbid_resolved = await aggregator.resolve_identifier(
        "123e4567-e89b-12d3-a456-426614174000",
        language="en",
    )

    assert entity.summary == "American jazz trumpeter."
    assert entity.external_ids.wikidata == "Q1150"
    assert entity.relations[0].target_name == "Charlie Parker"
    assert story.wikipedia_extract == "American jazz trumpeter."
    assert len(story.facts) >= 3
    assert resolved.name == "Miles Davis"
    assert searched[0].name == "Miles Davis"
    assert mbid_resolved.name == "Miles Davis"


@pytest.mark.asyncio
async def test_aggregator_scene_story_and_helpers() -> None:
    aggregator = EntityAggregator(FakeMusicBrainz(), FakeWikipedia())
    story = await aggregator.build_scene_story("detroit-techno", language="en")

    release_children = _children_from_payload(
        EntityType.RELEASE,
        {
            "media": [
                {
                    "tracks": [
                        {
                            "title": "So What",
                            "number": "1",
                            "position": 1,
                            "length": 540000,
                            "recording": {"id": "recording-1"},
                        }
                    ]
                }
            ]
        },
    )
    work_children = _children_from_payload(
        EntityType.WORK,
        {
            "relations": [
                {
                    "type": "performance",
                    "recording": {"id": "recording-2", "title": "Blue in Green"},
                }
            ]
        },
    )
    recording_children = _children_from_payload(
        EntityType.RECORDING,
        {"releases": [{"id": "release-1", "title": "Kind of Blue", "date": "1959-08-17"}]},
    )
    relations = _relations_from_payload(
        {
            "relations": [
                {
                    "type": "member of band",
                    "direction": "forward",
                    "artist": {"id": "artist-2", "name": "John Coltrane"},
                }
            ]
        }
    )
    external_ids = _extract_external_ids(
        [
            {"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Q1150"}},
            {"type": "wikipedia", "url": {"resource": "https://en.wikipedia.org/wiki/Miles_Davis"}},
            {"type": "discogs", "url": {"resource": "https://www.discogs.com/artist/23755"}},
            {"type": "streaming music", "url": {"resource": "https://open.spotify.com/artist/abc"}},
            {"type": "social network", "url": {"resource": "https://genius.com/artists/Miles-Davis"}},
            {"type": "purchase for download", "url": {"resource": "https://music.apple.com/us/artist/miles/1"}},
            {"type": "free streaming", "url": {"resource": "https://www.deezer.com/us/artist/111"}},
            {"type": "streaming", "url": {"resource": "https://tidal.com/browse/artist/222"}},
        ]
    )
    sample_entity = Entity(
        type=EntityType.ARTIST,
        name="Miles Davis",
        primary_date="1926-05-26",
        country="US",
        relations=relations,
    )
    facts = _facts_from_entity(sample_entity)

    assert story.entity_ref.name == "Detroit Techno"
    assert release_children[0].mbid == "recording-1"
    assert work_children[0].name == "Blue in Green"
    assert recording_children[0].primary_date == "1959-08-17"
    assert relations[0].direction == "forward"
    assert external_ids.wikidata == "Q1150"
    assert external_ids.wikipedia == "https://en.wikipedia.org/wiki/Miles_Davis"
    assert external_ids.spotify == "https://open.spotify.com/artist/abc"
    assert external_ids.genius == "https://genius.com/artists/Miles-Davis"
    assert external_ids.apple_music == "https://music.apple.com/us/artist/miles/1"
    assert external_ids.deezer == "https://www.deezer.com/us/artist/111"
    assert external_ids.tidal == "https://tidal.com/browse/artist/222"
    assert facts[0].date == "1926-05-26"
    assert _extract_mbid_from_identifier("https://musicbrainz.org/artist/123e4567-e89b-12d3-a456-426614174000")
    assert _primary_date({"life-span": {"begin": "1926-05-26"}}) == "1926-05-26"
    assert _primary_date({"date": "1959"}) == "1959"
    assert _country({"area": {"name": "United States"}}) == "United States"
    assert _first_str({"comment": "disambiguation"}, "disambiguation", "comment") == "disambiguation"
    assert _coalesce(None, "", "value") == "value"
    assert _nested_get({"a": {"b": {"c": 3}}}, "a", "b", "c") == 3
    assert _title_from_wikipedia_url("https://en.wikipedia.org/wiki/Miles_Davis") == "Miles_Davis"
