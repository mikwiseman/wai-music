"""Composition of the day tooling."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date as date_type
from typing import cast

from mcp.server.fastmcp import FastMCP

from wai_music.data import (
    MustHearEntry,
    SceneEntry,
    load_must_hear,
    load_scenes,
    load_seasonal_tags,
)
from wai_music.languages import validate_language
from wai_music.models import DailyMode, DailyPick, Entity, EntityType
from wai_music.services import ServiceContainer


@dataclass(frozen=True)
class DailySelection:
    entity: Entity
    angle: str
    rationale: str


class DailyPicker:
    def __init__(self, services: ServiceContainer) -> None:
        self._services = services
        self._must_hear = load_must_hear()
        self._scenes = tuple(load_scenes().values())
        self._seasonal = load_seasonal_tags()

    async def pick(
        self,
        *,
        mode: str | None = None,
        current_date: date_type | None = None,
        language: str,
    ) -> DailyPick:
        target_date = current_date or date_type.today()
        selected_mode = self._validated_mode(mode or self._default_mode_for_date(target_date))
        selection = getattr(self, f"_pick_{selected_mode.replace('-', '_')}")(target_date)
        entity = await self._materialize_entity(selection.entity, language=language)
        angle = _localized_angle(selection.angle, language=language)
        rationale = _localized_rationale(
            selected_mode, target_date, selection.rationale, language=language
        )
        return DailyPick(
            entity=entity,
            mode=selected_mode,
            angle=angle,
            rationale=rationale,
            suggested_actions=_localized_actions(language=language),
        )

    def _default_mode_for_date(self, current_date: date_type) -> str:
        modes = [
            "anniversary",
            "seasonal",
            "scene_dive",
            "chronological",
            "random_curated",
        ]
        return modes[current_date.toordinal() % len(modes)]

    def _validated_mode(self, mode: str) -> DailyMode:
        allowed = {
            "anniversary",
            "seasonal",
            "scene_dive",
            "chronological",
            "random_curated",
        }
        if mode not in allowed:
            raise ValueError(f"unsupported daily mode: {mode}")
        return cast(DailyMode, mode)

    def _pick_anniversary(self, current_date: date_type) -> DailySelection:
        calendar_seed = _calendar_seed(current_date)
        eligible = [entry for entry in self._must_hear if entry.year is not None]
        entry = eligible[calendar_seed % len(eligible)]
        years_since = current_date.year - entry.year if entry.year is not None else None
        years_suffix = (
            f" Roughly {years_since} years on from its release year."
            if years_since is not None
            else ""
        )
        return DailySelection(
            entity=_entity_from_must_hear(entry),
            angle="Calendar resonance",
            rationale=(
                f"A calendar-stable pick for {current_date.strftime('%B %d')}.{years_suffix}"
            ).strip(),
        )

    def _pick_seasonal(self, current_date: date_type) -> DailySelection:
        season = _season_for_month(current_date.month)
        preferred_genres = self._seasonal.get("season", {}).get(season, [])
        entry = next(
            (item for item in self._must_hear if item.genre in preferred_genres),
            self._must_hear[current_date.toordinal() % len(self._must_hear)],
        )
        return DailySelection(
            entity=_entity_from_must_hear(entry),
            angle=f"{season.title()} listening",
            rationale=f"This pick follows the seasonal mood tags curated for {season}.",
        )

    def _pick_scene_dive(self, current_date: date_type) -> DailySelection:
        scene = self._scenes[current_date.toordinal() % len(self._scenes)]
        return DailySelection(
            entity=_entity_from_scene(scene),
            angle=scene.curated_angles[0] if scene.curated_angles else "Scene fundamentals",
            rationale=f"A scene-focused selection drawn from {scene.name}.",
        )

    def _pick_chronological(self, current_date: date_type) -> DailySelection:
        ordered = sorted(self._must_hear, key=lambda item: item.year or 0)
        entry = ordered[_calendar_seed(current_date) % len(ordered)]
        return DailySelection(
            entity=_entity_from_must_hear(entry),
            angle="Chronological thread",
            rationale="A curated step through the timeline of recorded music.",
        )

    def _pick_random_curated(self, current_date: date_type) -> DailySelection:
        generator = random.Random(current_date.isoformat())
        entry = generator.choice(self._must_hear)
        return DailySelection(
            entity=_entity_from_must_hear(entry),
            angle="Wildcard essential",
            rationale="A seeded random pick from the cross-genre must-hear list.",
        )

    async def _materialize_entity(self, entity: Entity, *, language: str) -> Entity:
        if entity.type is EntityType.SCENE:
            scene_key = entity.metadata.get("scene_key")
            if isinstance(scene_key, str):
                story = await self._services.aggregator.build_scene_story(
                    scene_key, language=language
                )
                return story.entity_ref
            return entity

        curated_metadata = dict(entity.metadata)
        if entity.mbid:
            resolved = await self._services.aggregator.aggregate_entity(
                entity.mbid,
                entity.type,
                language=language,
            )
            resolved.metadata = {**curated_metadata, **resolved.metadata}
            return resolved

        query = _daily_lookup_query(entity)
        if query is None:
            return entity

        matches = await self._services.aggregator.search_entities(
            query,
            entity.type,
            limit=1,
        )
        if not matches:
            return entity
        match = matches[0]
        resolved = (
            await self._services.aggregator.aggregate_entity(
                match.mbid, match.type, language=language
            )
            if match.mbid
            else match
        )
        resolved.metadata = {**curated_metadata, **resolved.metadata}
        if resolved.summary is None and entity.summary is not None:
            resolved.summary = entity.summary
        return resolved


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
        metadata={"genre": entry.genre, "importance": entry.importance, "artist": entry.artist},
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


def _season_for_month(month: int) -> str:
    if month in {12, 1, 2}:
        return "winter"
    if month in {3, 4, 5}:
        return "spring"
    if month in {6, 7, 8}:
        return "summer"
    return "autumn"


async def composition_pick(
    *,
    services: ServiceContainer,
    mode: str | None = None,
    date: str | None = None,
    language: str | None = None,
) -> DailyPick:
    resolved_language = validate_language(language, default=services.settings.default_language)
    picker = DailyPicker(services)
    target_date = date_type.fromisoformat(date) if date else None
    return await picker.pick(mode=mode, current_date=target_date, language=resolved_language)


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool()
    async def composition_of_the_day(
        mode: str | None = None,
        date: str | None = None,
        language: str | None = None,
    ) -> DailyPick:
        """Return a daily music pick in one of five curated modes."""

        return await composition_pick(services=services, mode=mode, date=date, language=language)


def _calendar_seed(current_date: date_type) -> int:
    return (current_date.month * 100) + current_date.day


def _daily_lookup_query(entity: Entity) -> str | None:
    artist = entity.metadata.get("artist")
    if isinstance(artist, str) and artist:
        return f"{artist} {entity.name}"
    if entity.name:
        return entity.name
    return None


def _localized_angle(angle: str, *, language: str) -> str:
    if language != "ru":
        return angle
    if angle == "Calendar resonance":
        return "Календарный резонанс"
    if angle.endswith(" listening"):
        season = angle.removesuffix(" listening")
        translations = {
            "Winter": "Зимнее прослушивание",
            "Spring": "Весеннее прослушивание",
            "Summer": "Летнее прослушивание",
            "Autumn": "Осеннее прослушивание",
        }
        return translations.get(season, angle)
    if angle == "Chronological thread":
        return "Хронологическая нить"
    if angle == "Wildcard essential":
        return "Случайный essential"
    return angle


def _localized_rationale(
    mode: DailyMode,
    current_date: date_type,
    rationale: str,
    *,
    language: str,
) -> str:
    if language != "ru":
        return rationale
    if mode == "anniversary":
        return f"Календарно-стабильный выбор на {current_date.strftime('%d.%m')} из кураторского списка."
    if mode == "seasonal":
        return "Этот выбор следует сезонным mood-тегам, подготовленным для текущего времени года."
    if mode == "scene_dive":
        return "Выбор сфокусирован на сцене или движении и дает точку входа в контекст."
    if mode == "chronological":
        return "Кураторский шаг по хронологической линии истории записанной музыки."
    return "Детерминированно случайный выбор из кросс-жанрового must-hear списка."


def _localized_actions(*, language: str) -> list[str]:
    if language == "ru":
        return [
            "Открой связанную историю, чтобы углубить исторический контекст.",
            "Найди запись в backend и сохрани notes по этой карточке.",
        ]
    return [
        "Get the related story for deeper historical context.",
        "Find a backend recording and save notes for the pick.",
    ]
