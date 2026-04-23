"""Public Pydantic models exported by wai_music."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EntityType(StrEnum):
    ARTIST = "artist"
    RELEASE = "release"
    RECORDING = "recording"
    WORK = "work"
    SCENE = "scene"


class ExternalIds(BaseModel):
    musicbrainz: str | None = None
    spotify: str | None = None
    wikidata: str | None = None
    discogs: str | None = None
    genius: str | None = None
    open_opus: str | None = None
    apple_music: str | None = None
    deezer: str | None = None
    tidal: str | None = None
    yandex_music: str | None = None
    isni: str | None = None
    wikipedia: str | None = None


class ImageRef(BaseModel):
    url: str
    kind: str | None = None
    width: int | None = None
    height: int | None = None
    source: str | None = None


class RelationRef(BaseModel):
    kind: str
    target_name: str
    target_mbid: str | None = None
    direction: Literal["forward", "backward", "undirected"] = "undirected"


class Entity(BaseModel):
    model_config = ConfigDict(title="Entity")

    type: EntityType
    name: str
    mbid: str | None = None
    external_ids: ExternalIds = Field(default_factory=ExternalIds)
    summary: str | None = None
    images: list[ImageRef] = Field(default_factory=list)
    primary_date: str | None = None
    country: str | None = None
    disambiguation: str | None = None
    tags: list[str] = Field(default_factory=list)
    artist_credit: list[str] = Field(default_factory=list)
    children: list[Entity] = Field(default_factory=list)
    relations: list[RelationRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


FactKind = Literal["event", "relation", "quote", "link"]


class Fact(BaseModel):
    kind: FactKind
    label: str
    date: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None


class Story(BaseModel):
    entity_ref: Entity
    facts: list[Fact] = Field(default_factory=list)
    wikipedia_extract: str | None = None
    wikipedia_url: str | None = None
    language: str
    context_depth: Literal["full", "stub"] = "full"

    @model_validator(mode="after")
    def validate_payload(self) -> Story:
        if not self.facts and not self.wikipedia_extract:
            raise ValueError("story requires facts or wikipedia_extract")
        return self


class TrackQuery(BaseModel):
    backend: str = "spotify"
    query: str | None = None
    entity: Entity | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> TrackQuery:
        if not any([self.query, self.entity, self.title]):
            raise ValueError("track query requires query, entity, or title")
        return self


class TrackMatch(BaseModel):
    backend: str
    track_id: str
    uri: str | None = None
    url: str | None = None
    name: str
    artist_names: list[str] = Field(default_factory=list)
    album_name: str | None = None
    duration_ms: int | None = None
    popularity: int | None = None
    score: float | None = None
    external_ids: dict[str, str] = Field(default_factory=dict)


class TrackDetails(TrackMatch):
    explicit: bool | None = None
    preview_url: str | None = None
    release_date: str | None = None


class PlaylistRef(BaseModel):
    backend: str
    playlist_id: str
    name: str | None = None
    url: str | None = None


class PlaylistCreationResult(BaseModel):
    playlist: PlaylistRef
    added_track_ids: list[str] = Field(default_factory=list)
    public: bool = False


class ListeningProfile(BaseModel):
    top_artists: list[Entity] = Field(default_factory=list)
    top_tracks: list[TrackMatch] = Field(default_factory=list)
    saved_count: int = 0
    inferred_eras: list[str] = Field(default_factory=list)
    inferred_genres: list[str] = Field(default_factory=list)


DailyMode = Literal[
    "anniversary",
    "seasonal",
    "scene_dive",
    "chronological",
    "random_curated",
]


class DailyPick(BaseModel):
    entity: Entity
    mode: DailyMode
    angle: str
    rationale: str
    suggested_actions: list[str] = Field(default_factory=list)


class SavedNotes(BaseModel):
    path: str
    slug: str
    playlist_ref: PlaylistRef | None = None
    entities: list[Entity] = Field(default_factory=list)


__all__ = [
    "DailyMode",
    "DailyPick",
    "Entity",
    "EntityType",
    "ExternalIds",
    "Fact",
    "ImageRef",
    "ListeningProfile",
    "PlaylistCreationResult",
    "PlaylistRef",
    "RelationRef",
    "SavedNotes",
    "Story",
    "TrackDetails",
    "TrackMatch",
    "TrackQuery",
]
