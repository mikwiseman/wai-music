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

    def pick(self, *, mode: str | None = None, current_date: date_type | None = None) -> DailyPick:
        target_date = current_date or date_type.today()
        selected_mode = self._validated_mode(mode or self._default_mode_for_date(target_date))
        selection = getattr(self, f"_pick_{selected_mode.replace('-', '_')}")(target_date)
        return DailyPick(
            entity=selection.entity,
            mode=selected_mode,
            angle=selection.angle,
            rationale=selection.rationale,
            suggested_actions=[
                "Get the related story for deeper historical context.",
                "Find a backend recording and save notes for the pick.",
            ],
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
        entry = self._must_hear[current_date.toordinal() % len(self._must_hear)]
        return DailySelection(
            entity=_entity_from_must_hear(entry),
            angle="Calendar resonance",
            rationale=f"An archival pick keyed to the calendar cadence of {current_date.isoformat()}.",
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
        entry = ordered[current_date.toordinal() % len(ordered)]
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
) -> DailyPick:
    picker = DailyPicker(services)
    target_date = date_type.fromisoformat(date) if date else None
    return picker.pick(mode=mode, current_date=target_date)


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool()
    async def composition_of_the_day(
        mode: str | None = None,
        date: str | None = None,
        language: str | None = None,
    ) -> DailyPick:
        """Return a daily music pick in one of five curated modes."""

        _ = language
        return await composition_pick(services=services, mode=mode, date=date)
