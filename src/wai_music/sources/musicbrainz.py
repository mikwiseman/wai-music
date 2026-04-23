"""MusicBrainz source client."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from wai_music.cache import SQLiteCache
from wai_music.http import JsonHttpClient
from wai_music.models import EntityType
from wai_music.settings import WaiMusicSettings

ENTITY_PLURALS: dict[EntityType, str] = {
    EntityType.ARTIST: "artists",
    EntityType.RELEASE: "releases",
    EntityType.RECORDING: "recordings",
    EntityType.WORK: "works",
}


DEFAULT_INCLUDES: dict[EntityType, tuple[str, ...]] = {
    EntityType.ARTIST: ("aliases", "tags", "url-rels", "artist-rels", "release-groups"),
    EntityType.RELEASE: ("artist-credits", "recordings", "labels", "url-rels"),
    EntityType.RECORDING: ("artist-credits", "releases", "url-rels", "work-rels", "artist-rels"),
    EntityType.WORK: ("artist-rels", "url-rels", "recording-rels"),
}


class MusicBrainzSource:
    def __init__(
        self,
        *,
        settings: WaiMusicSettings,
        cache: SQLiteCache | None = None,
        client: JsonHttpClient | None = None,
    ) -> None:
        self._settings = settings
        self._cache = cache
        self._client = client or JsonHttpClient(
            base_url="https://musicbrainz.org/ws/2",
            headers={"User-Agent": settings.musicbrainz_user_agent},
            timeout=settings.http_timeout_seconds,
        )
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._interval = 1 / settings.musicbrainz_rate_limit_per_second

    async def close(self) -> None:
        await self._client.close()

    async def search(
        self,
        entity_type: EntityType,
        query: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        payload = await self._request_json(
            f"/{entity_type.value}",
            params={"query": query, "fmt": "json", "limit": str(limit)},
            ttl_seconds=30 * 24 * 60 * 60,
        )
        results = payload.get(ENTITY_PLURALS[entity_type], [])
        return [item for item in results if isinstance(item, dict)]

    async def lookup(
        self,
        entity_type: EntityType,
        mbid: str,
        *,
        includes: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        inc_value = "+".join(includes or DEFAULT_INCLUDES[entity_type])
        payload = await self._request_json(
            f"/{entity_type.value}/{mbid}",
            params={"fmt": "json", "inc": inc_value},
            ttl_seconds=30 * 24 * 60 * 60,
        )
        return payload

    async def probe(self, mbid: str) -> tuple[EntityType, dict[str, Any]] | None:
        for entity_type in (
            EntityType.ARTIST,
            EntityType.RELEASE,
            EntityType.RECORDING,
            EntityType.WORK,
        ):
            try:
                payload = await self.lookup(entity_type, mbid)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {400, 404}:
                    continue
                raise
            return entity_type, payload
        return None

    async def resolve_url(self, resource: str) -> list[dict[str, str]]:
        normalized = _normalize_lookup_resource(resource)
        search_term = _search_term(normalized)
        payload = await self._request_json(
            "/url",
            params={"query": search_term, "fmt": "json", "limit": "25"},
            ttl_seconds=30 * 24 * 60 * 60,
        )
        matches: list[dict[str, str]] = []
        for item in payload.get("urls", []):
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("resource", ""))
            if _normalize_lookup_resource(candidate) != normalized:
                continue
            for relation_group in item.get("relation-list", []):
                relations = (
                    relation_group.get("relations", []) if isinstance(relation_group, dict) else []
                )
                for relation in relations:
                    if not isinstance(relation, dict):
                        continue
                    entity_type = _relation_target_type(relation)
                    target = relation.get(entity_type)
                    if entity_type and isinstance(target, dict):
                        target_id = target.get("id")
                        target_name = target.get("name") or target.get("title")
                        if isinstance(target_id, str) and isinstance(target_name, str):
                            matches.append(
                                {
                                    "entity_type": entity_type,
                                    "mbid": target_id,
                                    "name": target_name,
                                    "relation_type": str(relation.get("type", "")),
                                }
                            )
        unique_matches: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for match in matches:
            key = (match["entity_type"], match["mbid"])
            if key in seen:
                continue
            seen.add(key)
            unique_matches.append(match)
        return unique_matches

    async def _request_json(
        self,
        path: str,
        *,
        params: dict[str, str],
        ttl_seconds: int,
    ) -> dict[str, Any]:
        cache_key = f"{path}?{urlencode(sorted(params.items()))}"
        if self._cache is not None:
            cached = self._cache.get_json(cache_key)
            if isinstance(cached, dict):
                return cached

        async with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._interval:
                await asyncio.sleep(self._interval - elapsed)
            payload = await self._client.request_json("GET", path, params=params)
            self._last_request_at = time.monotonic()

        if self._cache is not None:
            self._cache.set_json(cache_key, payload, ttl_seconds)
        return payload


def _normalize_lookup_resource(resource: str) -> str:
    if resource.startswith("spotify:"):
        _, entity_kind, entity_id = resource.split(":", 2)
        return f"https://open.spotify.com/{entity_kind}/{entity_id}"
    if resource.startswith("Q") and resource[1:].isdigit():
        return f"https://www.wikidata.org/wiki/{resource}"
    parsed = urlparse(resource)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    return resource.rstrip("/")


def _search_term(resource: str) -> str:
    parsed = urlparse(resource)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.netloc}{parsed.path}"
    return resource


def _relation_target_type(relation: dict[str, Any]) -> str | None:
    for key in ("artist", "release", "recording", "work"):
        if key in relation:
            return key
    return None
