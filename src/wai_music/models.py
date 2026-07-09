"""Public Pydantic models exported by wai_music."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    context_depth: Literal["full", "stub"] = "stub"

    @model_validator(mode="after")
    def validate_payload(self) -> Story:
        if not self.facts and not self.wikipedia_extract:
            raise ValueError("story requires facts or wikipedia_extract")
        if self.wikipedia_extract and self.context_depth == "stub":
            self.context_depth = "full"
        if self.context_depth == "full" and not self.wikipedia_extract:
            raise ValueError("full story requires wikipedia_extract")
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


MusicFinderIntent = Literal[
    "playlist",
    "track",
    "album",
    "artist",
    "scene",
    "daily_pick",
]

MusicFinderSource = Literal[
    "curated",
    "spotify_profile",
    "manual_seed",
    "scene_dive",
]

DiscoveryDepth = Literal["familiar", "balanced", "adventurous"]


class MusicFinderChoices(BaseModel):
    model_config = ConfigDict(title="MusicFinderChoices")

    intent: MusicFinderIntent = "playlist"
    source: MusicFinderSource = "curated"
    query: str | None = None
    genres: list[str] = Field(default_factory=list)
    moods: list[str] = Field(default_factory=list)
    scene_keys: list[str] = Field(default_factory=list)
    artists: list[str] = Field(default_factory=list)
    eras: list[str] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    energy: int | None = Field(default=None, ge=0, le=100)
    discovery_depth: DiscoveryDepth = "balanced"
    include_tracks: bool = True
    use_listening_profile: bool = False
    time_range: str = "medium_term"
    limit: int = Field(default=5, ge=1, le=20)
    language: str | None = None

    @field_validator(
        "genres",
        "moods",
        "scene_keys",
        "artists",
        "eras",
        "formats",
        "avoid",
        mode="before",
    )
    @classmethod
    def normalize_terms(cls, value: object) -> list[str]:
        if value is None:
            return []
        raw_items = value if isinstance(value, list) else [value]
        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            if not isinstance(item, str):
                continue
            term = " ".join(item.strip().lower().split())
            if term and term not in seen:
                seen.add(term)
                normalized.append(term)
        return normalized

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        normalized = " ".join(value.strip().split())
        return normalized or None


class MusicFinderCandidate(BaseModel):
    model_config = ConfigDict(title="MusicFinderCandidate")

    rank: int = Field(ge=1)
    entity: Entity
    track: TrackMatch | None = None
    score: float
    reasons: list[str] = Field(default_factory=list)
    matched_choices: list[str] = Field(default_factory=list)
    source: Literal["curated", "scene", "search", "profile"]
    spotify_query: str | None = None


class MusicFinderResult(BaseModel):
    model_config = ConfigDict(title="MusicFinderResult")

    choices: MusicFinderChoices
    candidates: list[MusicFinderCandidate] = Field(default_factory=list)
    profile_summary: ListeningProfile | None = None
    mcp_prompt: str


CatalogStatus = Literal["active", "available", "planned"]


class CatalogSignal(BaseModel):
    model_config = ConfigDict(title="CatalogSignal")

    key: str
    name: str
    status: CatalogStatus
    role: str
    best_for: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    tool_hint: str | None = None
    requires: list[str] = Field(default_factory=list)
    source_url: str | None = None


WorkflowStepStatus = Literal["ready", "optional", "requires_connection", "planned"]


class DiscoveryWorkflowStep(BaseModel):
    model_config = ConfigDict(title="DiscoveryWorkflowStep")

    label: str
    tool_names: list[str] = Field(default_factory=list)
    reason: str
    status: WorkflowStepStatus = "ready"


class MusicDiscoveryPlan(BaseModel):
    model_config = ConfigDict(title="MusicDiscoveryPlan")

    choices: MusicFinderChoices
    result: MusicFinderResult
    catalogs: list[CatalogSignal] = Field(default_factory=list)
    workflow_steps: list[DiscoveryWorkflowStep] = Field(default_factory=list)
    mcp_prompt: str


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
    "CatalogSignal",
    "CatalogStatus",
    "DailyMode",
    "DailyPick",
    "DiscoveryDepth",
    "DiscoveryWorkflowStep",
    "Entity",
    "EntityType",
    "ExternalIds",
    "Fact",
    "ImageRef",
    "ListeningProfile",
    "MusicDiscoveryPlan",
    "MusicFinderCandidate",
    "MusicFinderChoices",
    "MusicFinderIntent",
    "MusicFinderResult",
    "MusicFinderSource",
    "PlaylistCreationResult",
    "PlaylistRef",
    "RelationRef",
    "SavedNotes",
    "Story",
    "TrackDetails",
    "TrackMatch",
    "TrackQuery",
    "WorkflowStepStatus",
]
