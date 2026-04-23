"""Curated data loading helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).with_name("data")


@dataclass(frozen=True)
class SceneEntry:
    key: str
    name: str
    years: str
    countries: tuple[str, ...]
    anchor_artists_mbids: tuple[str, ...]
    description_short: str
    wikipedia_key: str | None
    curated_angles: tuple[str, ...]


@dataclass(frozen=True)
class MustHearEntry:
    mbid: str | None
    kind: str
    genre: str
    year: int | None
    importance: int
    name: str
    artist: str | None = None


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_scenes() -> dict[str, SceneEntry]:
    payload = _load_json(DATA_DIR / "scenes.json")
    return {
        item["key"]: SceneEntry(
            key=item["key"],
            name=item["name"],
            years=item["years"],
            countries=tuple(item.get("countries", [])),
            anchor_artists_mbids=tuple(item.get("anchor_artists_mbids", [])),
            description_short=item["description_short"],
            wikipedia_key=item.get("wikipedia_key"),
            curated_angles=tuple(item.get("curated_angles", [])),
        )
        for item in payload
    }


@lru_cache(maxsize=1)
def load_must_hear() -> tuple[MustHearEntry, ...]:
    payload = _load_json(DATA_DIR / "must_hear.json")
    return tuple(
        MustHearEntry(
            mbid=item.get("mbid"),
            kind=item["kind"],
            genre=item["genre"],
            year=item.get("year"),
            importance=item["importance"],
            name=item["name"],
            artist=item.get("artist"),
        )
        for item in payload
    )


@lru_cache(maxsize=1)
def load_seasonal_tags() -> dict[str, Any]:
    payload = _load_json(DATA_DIR / "seasonal_tags.json")
    if not isinstance(payload, dict):
        raise ValueError("seasonal_tags.json must contain an object")
    return payload
