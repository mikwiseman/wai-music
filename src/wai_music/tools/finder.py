"""Choice-based music finder tooling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mcp.server.fastmcp import FastMCP

from wai_music.data import MustHearEntry, SceneEntry, load_must_hear, load_scenes
from wai_music.languages import validate_language
from wai_music.models import (
    Entity,
    EntityType,
    ListeningProfile,
    MusicFinderCandidate,
    MusicFinderChoices,
    MusicFinderResult,
    TrackMatch,
    TrackQuery,
)
from wai_music.services import ServiceContainer
from wai_music.tools.annotations import READ_ONLY_TOOL
from wai_music.tools.profile import build_profile

MOOD_GENRE_HINTS: dict[str, set[str]] = {
    "reflective": {"jazz", "folk", "classical", "electronic", "world"},
    "bittersweet": {"jazz", "folk", "pop", "rock"},
    "hopeful": {"pop", "world", "folk"},
    "focused": {"classical", "electronic", "jazz"},
    "calm": {"classical", "electronic", "world", "folk"},
    "energetic": {"rock", "hip-hop", "electronic", "world"},
    "warm": {"jazz", "soul", "world", "folk", "pop"},
}

LOW_ENERGY_GENRES = {"classical", "jazz", "folk", "electronic", "world"}
HIGH_ENERGY_GENRES = {"rock", "hip-hop", "electronic", "world", "pop"}
CandidateSource = Literal["curated", "scene", "search", "profile"]


@dataclass(frozen=True)
class _ScoredEntity:
    entity: Entity
    score: float
    reasons: tuple[str, ...]
    matched_choices: tuple[str, ...]
    source: CandidateSource
    spotify_query: str


async def find_music_for_choices(
    choices: MusicFinderChoices,
    *,
    services: ServiceContainer,
    backend: str = "spotify",
    limit: int | None = None,
    language: str | None = None,
) -> MusicFinderResult:
    """Rank music candidates from explicit user choices."""

    resolved_language = validate_language(
        language or choices.language,
        default=services.settings.default_language,
    )
    result_limit = limit if limit is not None else choices.limit
    profile: ListeningProfile | None = None
    profile_genres: set[str] = set()
    profile_artists: set[str] = set()
    if choices.use_listening_profile:
        profile = await build_profile(backend, services=services, time_range=choices.time_range)
        profile_genres = set(profile.inferred_genres)
        profile_artists = {_normalize_text(artist.name) for artist in profile.top_artists}

    scored = _score_curated_entries(choices, profile_genres, profile_artists)
    scored.extend(_score_scenes(choices, profile_genres))
    scored.sort(key=lambda candidate: candidate.score, reverse=True)
    deduped = _dedupe_scored(scored)[:result_limit]

    track_matches: dict[str, TrackMatch | None] = {}
    if choices.include_tracks:
        playback_backend = services.backends.get(backend)
        for item in deduped:
            matches = await playback_backend.search_track(TrackQuery(query=item.spotify_query))
            track_matches[item.spotify_query] = matches[0] if matches else None

    candidates = [
        MusicFinderCandidate(
            rank=index,
            entity=item.entity,
            track=track_matches.get(item.spotify_query),
            score=round(item.score, 2),
            reasons=list(item.reasons),
            matched_choices=list(item.matched_choices),
            source=item.source,
            spotify_query=item.spotify_query,
        )
        for index, item in enumerate(deduped, start=1)
    ]
    return MusicFinderResult(
        choices=choices,
        candidates=candidates,
        profile_summary=profile,
        mcp_prompt=build_music_finder_prompt(choices, backend=backend, language=resolved_language),
    )


def build_music_finder_prompt(
    choices: MusicFinderChoices,
    *,
    backend: str = "spotify",
    language: str = "en",
) -> str:
    """Build a concise prompt that a host LLM can use with the MCP tools."""

    lines = [
        "Use the wai-music MCP tools to find music for these choices.",
        f"intent: {choices.intent}",
        f"source: {choices.source}",
        f"backend: {backend}",
        f"language: {language}",
        f"discovery_depth: {choices.discovery_depth}",
    ]
    if choices.query:
        lines.append(f"seed: {choices.query}")
    if choices.genres:
        lines.append(f"genres: {', '.join(choices.genres)}")
    if choices.moods:
        lines.append(f"moods: {', '.join(choices.moods)}")
    if choices.eras:
        lines.append(f"eras: {', '.join(choices.eras)}")
    if choices.formats:
        lines.append(f"formats: {', '.join(choices.formats)}")
    if choices.energy is not None:
        lines.append(f"energy: {choices.energy}/100")
    if choices.avoid:
        lines.append(f"avoid: {', '.join(choices.avoid)}")
    lines.append(
        "Return a short ranked list with why each pick matches, then use playlist tools only if I ask."
    )
    return "\n".join(lines)


def _score_curated_entries(
    choices: MusicFinderChoices,
    profile_genres: set[str],
    profile_artists: set[str],
) -> list[_ScoredEntity]:
    scored: list[_ScoredEntity] = []
    for entry in load_must_hear():
        candidate = _score_must_hear(entry, choices, profile_genres, profile_artists)
        if candidate is not None:
            scored.append(candidate)
    return scored


def _score_must_hear(
    entry: MustHearEntry,
    choices: MusicFinderChoices,
    profile_genres: set[str],
    profile_artists: set[str],
) -> _ScoredEntity | None:
    haystack = _normalize_text(
        " ".join(
            [
                entry.name,
                entry.artist or "",
                entry.genre,
                str(entry.year or ""),
                entry.kind,
            ]
        )
    )
    if _contains_avoided_term(haystack, choices.avoid):
        return None

    score = float(entry.importance * 10)
    reasons: list[str] = [f"curated importance {entry.importance}/10"]
    matched: list[str] = []

    if choices.genres and entry.genre in choices.genres:
        score += 35
        reasons.append(f"matches {entry.genre}")
        matched.append(entry.genre)
    if entry.genre in profile_genres:
        score += 18
        reasons.append("aligns with your Spotify genre signals")
        matched.append(f"profile:{entry.genre}")
    artist_key = _normalize_text(entry.artist or "")
    if artist_key and artist_key in profile_artists:
        score += 18
        reasons.append("connects to a top Spotify artist")
        matched.append(f"profile:{artist_key}")
    score += _query_score(haystack, choices.query, matched, reasons)
    score += _artist_score(artist_key, choices.artists, matched, reasons)
    score += _era_score(entry.year, choices.eras, matched, reasons)
    score += _format_score(entry.kind, choices.formats, matched, reasons)
    score += _mood_score(entry.genre, choices.moods, matched, reasons)
    score += _energy_score(entry.genre, choices.energy, reasons)
    score += _depth_score(entry.importance, choices.discovery_depth)

    return _ScoredEntity(
        entity=_entity_from_must_hear(entry),
        score=score,
        reasons=tuple(_dedupe_strings(reasons)[:4]),
        matched_choices=tuple(_dedupe_strings(matched)),
        source="curated",
        spotify_query=_spotify_query_from_entry(entry),
    )


def _score_scenes(choices: MusicFinderChoices, profile_genres: set[str]) -> list[_ScoredEntity]:
    scored: list[_ScoredEntity] = []
    for scene in load_scenes().values():
        haystack = _normalize_text(
            " ".join(
                [
                    scene.key,
                    scene.name,
                    scene.description_short,
                    scene.years,
                    " ".join(scene.countries),
                    " ".join(scene.curated_angles),
                ]
            )
        )
        if _contains_avoided_term(haystack, choices.avoid):
            continue
        score = 52.0
        reasons = ["scene context match"]
        matched: list[str] = []
        if scene.key in choices.scene_keys:
            score += 45
            reasons.append(f"matches scene {scene.name}")
            matched.append(scene.key)
        score += _query_score(haystack, choices.query, matched, reasons)
        for genre in choices.genres:
            if genre in haystack:
                score += 20
                reasons.append(f"connects to {genre}")
                matched.append(genre)
        for genre in profile_genres:
            if genre in haystack:
                score += 10
                reasons.append("aligns with your Spotify genre signals")
                matched.append(f"profile:{genre}")
        score += _mood_score_from_text(haystack, choices.moods, matched, reasons)
        if choices.source == "scene_dive":
            score += 18
        if score < 64 and choices.query:
            continue
        scored.append(
            _ScoredEntity(
                entity=_entity_from_scene(scene),
                score=score,
                reasons=tuple(_dedupe_strings(reasons)[:4]),
                matched_choices=tuple(_dedupe_strings(matched)),
                source="scene",
                spotify_query=scene.name,
            )
        )
    return scored


def _entity_from_must_hear(entry: MustHearEntry) -> Entity:
    entity_type = {
        "album": EntityType.RELEASE,
        "single": EntityType.RECORDING,
        "work": EntityType.WORK,
    }.get(entry.kind, EntityType.RELEASE)
    return Entity(
        type=entity_type,
        name=entry.name,
        mbid=entry.mbid,
        summary=f"{entry.genre.title()} essential" + (f" ({entry.year})" if entry.year else ""),
        metadata={
            "genre": entry.genre,
            "importance": entry.importance,
            "artist": entry.artist,
            "year": entry.year,
            "kind": entry.kind,
        },
    )


def _entity_from_scene(scene: SceneEntry) -> Entity:
    return Entity(
        type=EntityType.SCENE,
        name=scene.name,
        summary=scene.description_short,
        metadata={
            "scene_key": scene.key,
            "years": scene.years,
            "countries": list(scene.countries),
            "angles": list(scene.curated_angles),
        },
    )


def _spotify_query_from_entry(entry: MustHearEntry) -> str:
    parts = [entry.artist or "", entry.name]
    return " ".join(part for part in parts if part)


def _query_score(
    haystack: str,
    query: str | None,
    matched: list[str],
    reasons: list[str],
) -> float:
    if query is None:
        return 0.0
    query_key = _normalize_text(query)
    tokens = [token for token in query_key.split() if len(token) > 2]
    hits = [token for token in tokens if token in haystack]
    if not hits:
        return 0.0
    matched.extend(hits)
    reasons.append("matches your seed text")
    return min(24.0, float(len(hits) * 8))


def _artist_score(
    artist_key: str,
    artists: list[str],
    matched: list[str],
    reasons: list[str],
) -> float:
    if not artist_key:
        return 0.0
    for artist in artists:
        if artist in artist_key:
            matched.append(artist)
            reasons.append("matches requested artist")
            return 24.0
    return 0.0


def _era_score(
    year: int | None,
    eras: list[str],
    matched: list[str],
    reasons: list[str],
) -> float:
    if year is None:
        return 0.0
    for era in eras:
        if _year_in_era(year, era):
            matched.append(era)
            reasons.append(f"fits {era}")
            return 18.0
    return 0.0


def _format_score(
    kind: str,
    formats: list[str],
    matched: list[str],
    reasons: list[str],
) -> float:
    if not formats:
        return 0.0
    normalized_kind = "album" if kind == "album" else "track" if kind == "single" else kind
    if normalized_kind in formats or kind in formats:
        matched.append(normalized_kind)
        reasons.append(f"fits {normalized_kind} format")
        return 10.0
    return 0.0


def _mood_score(
    genre: str,
    moods: list[str],
    matched: list[str],
    reasons: list[str],
) -> float:
    score = 0.0
    for mood in moods:
        if genre in MOOD_GENRE_HINTS.get(mood, set()):
            score += 8.0
            matched.append(mood)
    if score:
        reasons.append("fits the selected mood")
    return min(score, 18.0)


def _mood_score_from_text(
    haystack: str,
    moods: list[str],
    matched: list[str],
    reasons: list[str],
) -> float:
    score = 0.0
    for mood in moods:
        if mood in haystack:
            score += 8.0
            matched.append(mood)
    if score:
        reasons.append("fits the selected mood")
    return min(score, 18.0)


def _energy_score(genre: str, energy: int | None, reasons: list[str]) -> float:
    if energy is None:
        return 0.0
    if energy <= 40 and genre in LOW_ENERGY_GENRES:
        reasons.append("works for lower-energy listening")
        return 7.0
    if energy >= 70 and genre in HIGH_ENERGY_GENRES:
        reasons.append("works for high-energy listening")
        return 7.0
    if 40 < energy < 70:
        return 4.0
    return 0.0


def _depth_score(importance: int, discovery_depth: str) -> float:
    if discovery_depth == "familiar":
        return float(importance)
    if discovery_depth == "adventurous":
        return float(max(0, 10 - importance) * 3)
    return 5.0


def _year_in_era(year: int, era: str) -> bool:
    if era.endswith("s") and len(era) >= 3:
        prefix = era[:-1]
        if prefix.isdigit():
            decade = int(prefix)
            if decade < 100:
                decade += 1900 if decade >= 30 else 2000
            return decade <= year <= decade + 9
    if "-" in era:
        start, end = era.split("-", maxsplit=1)
        if start.strip().isdigit() and end.strip().isdigit():
            return int(start) <= year <= int(end)
    return str(year) == era


def _contains_avoided_term(haystack: str, avoid: list[str]) -> bool:
    return any(term and term in haystack for term in avoid)


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().strip().split())


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _dedupe_scored(candidates: list[_ScoredEntity]) -> list[_ScoredEntity]:
    deduped: list[_ScoredEntity] = []
    seen: set[tuple[str | None, str]] = set()
    for candidate in candidates:
        key = (candidate.entity.mbid, _normalize_text(candidate.entity.name))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool(annotations=READ_ONLY_TOOL)
    async def find_music(
        choices: MusicFinderChoices,
        backend: str = "spotify",
        limit: int | None = None,
        language: str | None = None,
    ) -> MusicFinderResult:
        """Find ranked music candidates from explicit user choices."""

        return await find_music_for_choices(
            choices,
            services=services,
            backend=backend,
            limit=limit,
            language=language,
        )
