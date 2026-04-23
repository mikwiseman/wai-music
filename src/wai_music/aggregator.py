"""Entity aggregation across sources."""

from __future__ import annotations

import re
from typing import Any, Literal, cast

from wai_music.data import load_scenes
from wai_music.models import Entity, EntityType, ExternalIds, Fact, ImageRef, RelationRef, Story
from wai_music.sources.musicbrainz import (
    DEFAULT_INCLUDES,
    MusicBrainzSource,
    _normalize_lookup_resource,
)
from wai_music.sources.wikipedia import WikipediaSource

MBID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class EntityAggregator:
    def __init__(self, musicbrainz: MusicBrainzSource, wikipedia: WikipediaSource) -> None:
        self._musicbrainz = musicbrainz
        self._wikipedia = wikipedia

    async def search_entities(
        self,
        query: str,
        entity_type: EntityType | None = None,
        *,
        limit: int = 5,
    ) -> list[Entity]:
        entity_types = (
            [entity_type]
            if entity_type is not None
            else [
                EntityType.ARTIST,
                EntityType.RELEASE,
                EntityType.RECORDING,
                EntityType.WORK,
            ]
        )
        results: list[Entity] = []
        for candidate_type in entity_types:
            raw_results = await self._musicbrainz.search(candidate_type, query, limit=limit)
            results.extend(
                self._entity_from_musicbrainz(candidate_type, item) for item in raw_results
            )
        results.sort(key=lambda item: int(item.metadata.get("score", 0)), reverse=True)
        return results[:limit]

    async def resolve_identifier(self, identifier: str, *, language: str = "en") -> Entity:
        mbid = _extract_mbid_from_identifier(identifier)
        if mbid is not None:
            entity_match = await self._musicbrainz.probe(mbid)
            if entity_match is None:
                raise ValueError(f"MusicBrainz entity not found for MBID {mbid}")
            entity_type, _payload = entity_match
            return await self.aggregate_entity(mbid, entity_type, language=language)

        matches = await self._musicbrainz.resolve_url(_normalize_lookup_resource(identifier))
        if not matches:
            raise ValueError(f"Could not resolve identifier: {identifier}")
        top_match = matches[0]
        return await self.aggregate_entity(
            top_match["mbid"],
            EntityType(top_match["entity_type"]),
            language=language,
        )

    async def aggregate_entity(
        self,
        mbid: str,
        entity_type: EntityType,
        *,
        language: str = "en",
    ) -> Entity:
        payload = await self._musicbrainz.lookup(
            entity_type,
            mbid,
            includes=DEFAULT_INCLUDES[entity_type],
        )
        entity = self._entity_from_musicbrainz(entity_type, payload)
        wiki_facts: dict[str, str | None] = {}

        if entity.external_ids.wikidata:
            wiki_facts = await self._wikipedia.get_wikidata_facts(
                entity.external_ids.wikidata, language=language
            )
        wikipedia_title = (
            _title_from_wikipedia_url(entity.external_ids.wikipedia)
            if entity.external_ids.wikipedia
            else wiki_facts.get("wikipedia_title")
        )
        if wikipedia_title:
            summary = await self._wikipedia.get_summary(wikipedia_title, language=language)
            if summary is not None:
                entity.summary = _coalesce(
                    summary.get("extract"), summary.get("description"), entity.summary
                )
                entity.metadata["wikipedia_url"] = _nested_get(
                    summary,
                    "content_urls",
                    "desktop",
                    "page",
                )
                thumbnail = summary.get("thumbnail")
                if isinstance(thumbnail, dict):
                    source = thumbnail.get("source")
                    if isinstance(source, str):
                        entity.images.append(
                            ImageRef(
                                url=source,
                                kind="thumbnail",
                                width=thumbnail.get("width")
                                if isinstance(thumbnail.get("width"), int)
                                else None,
                                height=thumbnail.get("height")
                                if isinstance(thumbnail.get("height"), int)
                                else None,
                                source="wikipedia",
                            )
                        )

        if wiki_facts:
            entity.metadata["wikidata_facts"] = wiki_facts
        return entity

    async def build_story(
        self,
        mbid: str,
        entity_type: EntityType,
        *,
        language: str = "en",
    ) -> Story:
        entity = await self.aggregate_entity(mbid, entity_type, language=language)
        facts = _facts_from_entity(entity)
        wikidata_facts = entity.metadata.get("wikidata_facts")
        if isinstance(wikidata_facts, dict):
            if isinstance(wikidata_facts.get("birth_date"), str):
                facts.append(
                    Fact(
                        kind="event",
                        label="Birth date",
                        date=wikidata_facts["birth_date"],
                        source="wikidata",
                    )
                )
            if isinstance(wikidata_facts.get("death_date"), str):
                facts.append(
                    Fact(
                        kind="event",
                        label="Death date",
                        date=wikidata_facts["death_date"],
                        source="wikidata",
                    )
                )
            if isinstance(wikidata_facts.get("inception_date"), str):
                facts.append(
                    Fact(
                        kind="event",
                        label="Inception date",
                        date=wikidata_facts["inception_date"],
                        source="wikidata",
                    )
                )
        return Story(
            entity_ref=entity,
            facts=facts,
            wikipedia_extract=entity.summary,
            wikipedia_url=entity.metadata.get("wikipedia_url")
            if isinstance(entity.metadata.get("wikipedia_url"), str)
            else None,
            language=language,
            context_depth="full" if entity.summary else "stub",
        )

    async def get_related(
        self,
        mbid: str,
        entity_type: EntityType,
        *,
        kind: str | None = None,
    ) -> list[RelationRef]:
        entity = await self.aggregate_entity(mbid, entity_type)
        if kind is None:
            return entity.relations
        return [relation for relation in entity.relations if relation.kind == kind]

    async def build_scene_story(self, scene_key: str, *, language: str = "en") -> Story:
        scene = load_scenes()[scene_key]
        entity = Entity(
            type=EntityType.SCENE,
            name=scene.name,
            summary=scene.description_short,
            metadata={
                "years": scene.years,
                "countries": list(scene.countries),
                "curated_angles": list(scene.curated_angles),
            },
        )
        summary = None
        wikipedia_url = None
        if scene.wikipedia_key:
            summary = await self._wikipedia.get_summary(scene.wikipedia_key, language=language)
            if summary is not None:
                entity.summary = _coalesce(summary.get("extract"), entity.summary)
                wikipedia_url = _nested_get(summary, "content_urls", "desktop", "page")
        facts = [
            Fact(kind="event", label="Period", date=scene.years, source="curated"),
            Fact(
                kind="link",
                label="Countries",
                data={"countries": list(scene.countries)},
                source="curated",
            ),
        ]
        for angle in scene.curated_angles[:3]:
            facts.append(
                Fact(kind="relation", label="Angle", data={"value": angle}, source="curated")
            )
        return Story(
            entity_ref=entity,
            facts=facts,
            wikipedia_extract=entity.summary,
            wikipedia_url=wikipedia_url if isinstance(wikipedia_url, str) else None,
            language=language,
            context_depth="full" if entity.summary else "stub",
        )

    def _entity_from_musicbrainz(self, entity_type: EntityType, payload: dict[str, Any]) -> Entity:
        external_ids = _extract_external_ids(payload.get("relations", []))
        name = payload.get("name") or payload.get("title") or "Unknown"
        entity = Entity(
            type=entity_type,
            name=str(name),
            mbid=payload.get("id") if isinstance(payload.get("id"), str) else None,
            external_ids=external_ids,
            primary_date=_primary_date(payload),
            country=_country(payload),
            disambiguation=_first_str(payload, "disambiguation", "comment"),
            tags=[
                item["name"]
                for item in payload.get("tags", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ],
            artist_credit=[
                item["name"]
                for item in payload.get("artist-credit", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ],
            children=_children_from_payload(entity_type, payload),
            relations=_relations_from_payload(payload),
            metadata={
                key: payload[key]
                for key in ("score", "type", "status", "language", "track-count")
                if key in payload
            },
        )
        if entity_type is EntityType.RELEASE and entity.mbid:
            entity.images.append(
                ImageRef(
                    url=f"https://coverartarchive.org/release/{entity.mbid}/front-250",
                    kind="cover",
                    source="coverartarchive",
                )
            )
        return entity


def _extract_mbid_from_identifier(identifier: str) -> str | None:
    if MBID_PATTERN.match(identifier):
        return identifier
    for segment in identifier.rstrip("/").split("/"):
        if MBID_PATTERN.match(segment):
            return segment
    return None


def _extract_external_ids(relations: Any) -> ExternalIds:
    external_ids = ExternalIds()
    if not isinstance(relations, list):
        return external_ids
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        url = relation.get("url")
        if not isinstance(url, dict):
            continue
        resource = url.get("resource")
        if not isinstance(resource, str):
            continue
        relation_type = relation.get("type")
        normalized = _normalize_lookup_resource(resource)
        if relation_type == "wikidata":
            external_ids.wikidata = normalized.rsplit("/", 1)[-1]
        elif relation_type == "wikipedia":
            external_ids.wikipedia = normalized
        elif relation_type == "discogs":
            external_ids.discogs = normalized
        elif "spotify.com" in normalized:
            external_ids.spotify = normalized
        elif "genius.com" in normalized:
            external_ids.genius = normalized
        elif "music.apple.com" in normalized:
            external_ids.apple_music = normalized
        elif "deezer.com" in normalized:
            external_ids.deezer = normalized
        elif "tidal.com" in normalized:
            external_ids.tidal = normalized
    return external_ids


def _primary_date(payload: dict[str, Any]) -> str | None:
    life_span = payload.get("life-span")
    if isinstance(life_span, dict):
        begin = life_span.get("begin")
        if isinstance(begin, str):
            return begin
    for key in ("date", "first-release-date"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return None


def _country(payload: dict[str, Any]) -> str | None:
    country = payload.get("country")
    if isinstance(country, str):
        return country
    area = payload.get("area")
    if isinstance(area, dict):
        area_name = area.get("name")
        if isinstance(area_name, str):
            return area_name
    return None


def _first_str(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return None


def _children_from_payload(entity_type: EntityType, payload: dict[str, Any]) -> list[Entity]:
    if entity_type is EntityType.RELEASE:
        children: list[Entity] = []
        for medium in payload.get("media", []):
            if not isinstance(medium, dict):
                continue
            for track in medium.get("tracks", []):
                if not isinstance(track, dict):
                    continue
                title = track.get("title")
                if not isinstance(title, str):
                    continue
                recording = (
                    track.get("recording") if isinstance(track.get("recording"), dict) else {}
                )
                if not isinstance(recording, dict):
                    recording = {}
                children.append(
                    Entity(
                        type=EntityType.RECORDING,
                        name=title,
                        mbid=recording.get("id") if isinstance(recording.get("id"), str) else None,
                        metadata={
                            "track_number": track.get("number"),
                            "position": track.get("position"),
                            "length": track.get("length"),
                        },
                    )
                )
        return children
    if entity_type is EntityType.WORK:
        children = []
        for relation in payload.get("relations", []):
            if isinstance(relation, dict) and relation.get("type") == "performance":
                recording = relation.get("recording")
                if isinstance(recording, dict):
                    title = recording.get("title")
                    if isinstance(title, str):
                        children.append(
                            Entity(
                                type=EntityType.RECORDING,
                                name=title,
                                mbid=recording.get("id")
                                if isinstance(recording.get("id"), str)
                                else None,
                            )
                        )
        return children
    if entity_type is EntityType.RECORDING:
        children = []
        for release in payload.get("releases", []):
            if isinstance(release, dict):
                title = release.get("title")
                if isinstance(title, str):
                    children.append(
                        Entity(
                            type=EntityType.RELEASE,
                            name=title,
                            mbid=release.get("id") if isinstance(release.get("id"), str) else None,
                            primary_date=release.get("date")
                            if isinstance(release.get("date"), str)
                            else None,
                        )
                    )
        return children
    return []


def _relations_from_payload(payload: dict[str, Any]) -> list[RelationRef]:
    relations: list[RelationRef] = []
    for relation in payload.get("relations", []):
        if not isinstance(relation, dict) or relation.get("target-type") == "url":
            continue
        target_type = None
        target = None
        for candidate in ("artist", "release", "recording", "work"):
            if candidate in relation and isinstance(relation[candidate], dict):
                target_type = candidate
                target = relation[candidate]
                break
        if target_type is None or not isinstance(target, dict):
            continue
        target_name = target.get("name") or target.get("title")
        target_mbid = target.get("id")
        if isinstance(target_name, str):
            direction_value = relation.get("direction")
            direction: Literal["forward", "backward", "undirected"]
            if direction_value in {"forward", "backward"}:
                direction = cast(Literal["forward", "backward"], direction_value)
            else:
                direction = "undirected"
            relations.append(
                RelationRef(
                    kind=str(relation.get("type", target_type)),
                    target_name=target_name,
                    target_mbid=target_mbid if isinstance(target_mbid, str) else None,
                    direction=direction,
                )
            )
    return relations


def _facts_from_entity(entity: Entity) -> list[Fact]:
    facts: list[Fact] = []
    if entity.primary_date:
        facts.append(
            Fact(kind="event", label="Primary date", date=entity.primary_date, source="musicbrainz")
        )
    if entity.country:
        facts.append(
            Fact(
                kind="link", label="Country", data={"country": entity.country}, source="musicbrainz"
            )
        )
    for relation in entity.relations[:6]:
        facts.append(
            Fact(
                kind="relation",
                label=relation.kind,
                data={"target_name": relation.target_name, "target_mbid": relation.target_mbid},
                source="musicbrainz",
            )
        )
    return facts


def _coalesce(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _nested_get(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _title_from_wikipedia_url(url: str) -> str:
    return url.rstrip("/").rsplit("/wiki/", 1)[-1]
