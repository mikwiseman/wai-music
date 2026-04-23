"""Wikipedia and Wikidata source client."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote, urlparse

from wai_music.cache import SQLiteCache
from wai_music.http import JsonHttpClient
from wai_music.settings import WaiMusicSettings


class WikipediaSource:
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
            headers={"User-Agent": settings.musicbrainz_user_agent},
            timeout=settings.http_timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.close()

    async def get_summary(
        self, title_or_url: str, *, language: str = "en"
    ) -> dict[str, Any] | None:
        title = _normalize_title(title_or_url)
        cache_key = f"wiki-summary:{language}:{title}"
        if self._cache is not None:
            cached = self._cache.get_json(cache_key)
            if isinstance(cached, dict):
                return cached
        path = f"https://{language}.wikipedia.org/api/rest_v1/page/summary/{quote(title, safe='')}"
        try:
            payload = await self._client.request_json(
                "GET",
                path,
                headers={"Accept": "application/json"},
            )
        except Exception:
            return None
        if self._cache is not None:
            self._cache.set_json(cache_key, payload, 7 * 24 * 60 * 60)
        return payload

    async def get_wikidata_facts(self, qid: str, *, language: str = "en") -> dict[str, str | None]:
        cache_key = f"wikidata-facts:{language}:{qid}"
        if self._cache is not None:
            cached = self._cache.get_json(cache_key)
            if isinstance(cached, dict):
                return {
                    key: value if isinstance(value, str) or value is None else None
                    for key, value in cached.items()
                }

        query = f"""
        SELECT ?itemLabel ?birth ?death ?inception ?article WHERE {{
          VALUES ?item {{ wd:{qid} }}
          OPTIONAL {{ ?item wdt:P569 ?birth . }}
          OPTIONAL {{ ?item wdt:P570 ?death . }}
          OPTIONAL {{ ?item wdt:P571 ?inception . }}
          OPTIONAL {{
            ?article schema:about ?item ;
                     schema:isPartOf <https://{language}.wikipedia.org/> .
          }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{language},en". }}
        }}
        LIMIT 1
        """.strip()
        payload = await self._client.request_json(
            "GET",
            "https://query.wikidata.org/sparql",
            params={"format": "json", "query": query},
            headers={"Accept": "application/sparql-results+json"},
        )
        bindings = payload.get("results", {}).get("bindings", [])
        binding = bindings[0] if bindings else {}
        article = binding.get("article", {}).get("value") if isinstance(binding, dict) else None
        facts = {
            "qid": qid,
            "label": _binding_value(binding, "itemLabel"),
            "birth_date": _binding_value(binding, "birth"),
            "death_date": _binding_value(binding, "death"),
            "inception_date": _binding_value(binding, "inception"),
            "wikipedia_title": _title_from_url(article) if isinstance(article, str) else None,
        }
        if self._cache is not None:
            self._cache.set_json(cache_key, facts, 30 * 24 * 60 * 60)
        return facts


def _binding_value(binding: dict[str, Any], key: str) -> str | None:
    value = binding.get(key)
    if isinstance(value, dict):
        candidate = value.get("value")
        return candidate if isinstance(candidate, str) else None
    return None


def _normalize_title(title_or_url: str) -> str:
    parsed = urlparse(title_or_url)
    if parsed.scheme and parsed.netloc and "/wiki/" in parsed.path:
        return unquote(parsed.path.rsplit("/wiki/", 1)[-1])
    return title_or_url.replace(" ", "_")


def _title_from_url(url: str) -> str:
    parsed = urlparse(url)
    return unquote(parsed.path.rsplit("/", 1)[-1])
