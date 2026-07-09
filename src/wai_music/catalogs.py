"""Catalog capability map and MCP workflow planning."""

from __future__ import annotations

import json
from typing import Any

from wai_music.models import (
    CatalogSignal,
    CatalogStatus,
    DiscoveryWorkflowStep,
    MusicFinderChoices,
    WorkflowStepStatus,
)

_CATALOG_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "curated",
        "name": "Wai curated",
        "role": "Editorial must-hear records and scene anchors for fast first-pass ranking.",
        "best_for": ["starter recommendations", "scene pivots", "demo-safe defaults"],
        "limitations": ["Small local dataset; not a complete streaming catalog."],
        "tool_hint": "find_music",
    },
    {
        "key": "musicbrainz",
        "name": "MusicBrainz",
        "role": "Canonical music IDs, release/work metadata, aliases, tags, and relationships.",
        "best_for": ["deduping entities", "artist/release/work lookup", "relationship traversal"],
        "limitations": ["Rate-limited public API; requires meaningful User-Agent."],
        "tool_hint": "search, resolve, get_related",
        "source_url": "https://musicbrainz.org/doc/MusicBrainz_API",
    },
    {
        "key": "wikipedia_wikidata",
        "name": "Wikipedia / Wikidata",
        "role": "Human-readable context plus SPARQL-backed dates, labels, and article links.",
        "best_for": ["artist stories", "scene context", "historical grounding"],
        "limitations": ["Coverage is uneven for niche recordings and local scenes."],
        "tool_hint": "get_artist_story, get_release_story, get_recording_story, get_scene_story",
        "source_url": "https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual",
    },
    {
        "key": "spotify",
        "name": "Spotify",
        "role": "User taste signals, playable search results, and playlist creation.",
        "best_for": ["listening profile", "track matching", "playlist writes"],
        "limitations": [
            "Requires each user to connect Spotify; write actions require explicit intent."
        ],
        "tool_hint": "get_listening_profile, find_track_on, create_playlist",
        "requires": ["spotify_connection"],
        "source_url": "https://developer.spotify.com/documentation/web-api",
    },
    {
        "key": "listenbrainz",
        "name": "ListenBrainz",
        "role": "Collaborative-filtering recommendations around MusicBrainz recording IDs.",
        "best_for": ["similar recordings", "open recommendation signals", "MBID-first discovery"],
        "limitations": ["Adapter is planned; production code does not call it yet."],
        "requires": ["listenbrainz_adapter"],
        "source_url": "https://listenbrainz.readthedocs.io/en/latest/users/api/recommendation.html",
    },
    {
        "key": "lastfm",
        "name": "Last.fm",
        "role": "Similar artists and community tag signals.",
        "best_for": ["artist similarity", "tag expansion", "mainstream-to-adjacent pivots"],
        "limitations": ["Requires an API key; adapter is planned."],
        "requires": ["lastfm_api_key", "lastfm_adapter"],
        "source_url": "https://www.last.fm/api/show/artist.getSimilar",
    },
    {
        "key": "discogs",
        "name": "Discogs",
        "role": "Labels, formats, catalog numbers, editions, and collector metadata.",
        "best_for": ["pressing context", "label trails", "format-aware digging"],
        "limitations": ["Requires API credentials for useful search volume; adapter is planned."],
        "requires": ["discogs_credentials", "discogs_adapter"],
        "source_url": "https://www.discogs.com/developers",
    },
)


def list_catalog_signals(
    choices: MusicFinderChoices | None = None,
    *,
    spotify_connected: bool = False,
    include_planned: bool = True,
) -> list[CatalogSignal]:
    """Return source capabilities for the current discovery context."""

    active_keys = _active_catalog_keys(choices, spotify_connected=spotify_connected)
    signals: list[CatalogSignal] = []
    for definition in _CATALOG_DEFINITIONS:
        key = str(definition["key"])
        if key in {"listenbrainz", "lastfm", "discogs"}:
            status: CatalogStatus = "planned"
        elif key == "spotify" and key not in active_keys:
            status = "available"
        else:
            status = "active" if key in active_keys else "available"
        if status == "planned" and not include_planned:
            continue
        signals.append(CatalogSignal(status=status, **definition))
    return signals


def build_discovery_workflow_steps(
    choices: MusicFinderChoices,
    *,
    spotify_connected: bool = False,
) -> list[DiscoveryWorkflowStep]:
    """Build a host-LLM-friendly plan from the available MCP surface."""

    profile_status: WorkflowStepStatus = "ready" if spotify_connected else "requires_connection"
    playlist_status: WorkflowStepStatus = "optional" if spotify_connected else "requires_connection"
    steps = [
        DiscoveryWorkflowStep(
            label="Rank candidates",
            tool_names=["find_music"],
            reason="Use explicit choices first, then return a short explainable list.",
        ),
        DiscoveryWorkflowStep(
            label="Resolve metadata",
            tool_names=["search", "resolve", "get_related"],
            reason="Pin recommendations to MusicBrainz IDs before deeper narration or similarity.",
        ),
        DiscoveryWorkflowStep(
            label="Add story context",
            tool_names=[
                "get_artist_story",
                "get_release_story",
                "get_recording_story",
                "get_scene_story",
            ],
            reason="Use Wikipedia and Wikidata facts only after the entity is resolved.",
        ),
        DiscoveryWorkflowStep(
            label="Blend user taste",
            tool_names=["get_listening_profile"],
            reason="Use Spotify top artists/tracks when the user asks for personal taste.",
            status=profile_status,
        ),
        DiscoveryWorkflowStep(
            label="Create playlist",
            tool_names=["find_track_on", "create_playlist", "add_tracks_to_playlist"],
            reason="Write to Spotify only after the user explicitly asks for a playlist.",
            status=playlist_status,
        ),
        DiscoveryWorkflowStep(
            label="Save evidence",
            tool_names=["save_notes"],
            reason="Persist the final recommendation trail, sources, and playlist reference locally.",
            status="optional",
        ),
    ]
    if choices.discovery_depth == "familiar":
        return [step for step in steps if step.label != "Add story context"]
    return steps


def build_discovery_workflow_prompt(
    *,
    choices: MusicFinderChoices,
    base_prompt: str,
    catalogs: list[CatalogSignal],
    steps: list[DiscoveryWorkflowStep],
) -> str:
    """Create a compact MCP prompt that includes source and safety boundaries."""

    active_catalogs = ", ".join(catalog.name for catalog in catalogs if catalog.status == "active")
    planned_catalogs = ", ".join(
        catalog.name for catalog in catalogs if catalog.status == "planned"
    )
    step_lines = [
        f"{index}. {step.label}: {', '.join(step.tool_names)} ({step.status})"
        for index, step in enumerate(steps, start=1)
    ]
    lines = [
        base_prompt,
        "",
        "Source priority:",
        f"active: {active_catalogs or 'none'}",
    ]
    if planned_catalogs:
        lines.append(f"planned, do not claim live access: {planned_catalogs}")
    lines.extend(
        [
            "",
            "Workflow:",
            *step_lines,
            "",
            "Do not create or modify playlists unless I explicitly ask for that write action.",
        ]
    )
    if choices.use_listening_profile or choices.source == "spotify_profile":
        lines.append(
            "If Spotify is not connected, ask me to connect it instead of guessing my profile."
        )
    return "\n".join(lines)


def catalog_map_json() -> str:
    """Serialize the full discovery catalog map for MCP resource reads."""

    return json.dumps(
        [signal.model_dump() for signal in list_catalog_signals(spotify_connected=False)],
        ensure_ascii=True,
        indent=2,
    )


def _active_catalog_keys(
    choices: MusicFinderChoices | None,
    *,
    spotify_connected: bool,
) -> set[str]:
    keys = {"curated", "musicbrainz", "wikipedia_wikidata"}
    if choices is None:
        return keys | ({"spotify"} if spotify_connected else set())
    if (
        choices.include_tracks
        or choices.use_listening_profile
        or choices.source == "spotify_profile"
    ):
        if spotify_connected or choices.include_tracks:
            keys.add("spotify")
    if choices.source == "scene_dive":
        keys.add("wikipedia_wikidata")
    return keys
