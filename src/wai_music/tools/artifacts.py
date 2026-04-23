"""Artifact generation tools."""

from __future__ import annotations

import os
import re
from datetime import datetime
from json import dumps as json_dumps

from mcp.server.fastmcp import FastMCP

from wai_music.auth.current import current_user_id
from wai_music.logging_config import get_logger
from wai_music.models import Entity, SavedNotes
from wai_music.services import ServiceContainer
from wai_music.tools.annotations import LOCAL_WRITE_TOOL

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
logger = get_logger(__name__)


def save_markdown_notes(
    slug: str,
    markdown: str,
    *,
    services: ServiceContainer,
    entities: list[Entity] | None = None,
) -> SavedNotes:
    if not SLUG_PATTERN.match(slug):
        raise ValueError("slug must match ^[a-z0-9]+(?:-[a-z0-9]+)*$")
    user_id = current_user_id()
    target_dir = services.settings.playlists_dir
    if user_id is not None:
        target_dir = target_dir / user_id
        target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{datetime.now().date().isoformat()}-{slug}.md"
    payload = _front_matter(slug, entities or [])
    contents = f"{payload}\n{markdown.strip()}\n"
    try:
        with target_path.open("x", encoding="utf-8") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        logger.warning(
            "save_notes_conflict",
            slug=slug,
            path=str(target_path),
            user_id=user_id,
        )
        raise FileExistsError(f"notes already exist for slug {slug!r} on this date") from exc
    logger.info(
        "save_notes_succeeded",
        slug=slug,
        path=str(target_path),
        user_id=user_id,
        entity_count=len(entities or []),
    )
    return SavedNotes(path=str(target_path), slug=slug, entities=entities or [])


def _front_matter(slug: str, entities: list[Entity]) -> str:
    lines = ["---", f"slug: {slug}", "entities:"]
    if not entities:
        lines.append("  []")
    for entity in entities:
        lines.append(f"  - type: {entity.type.value}")
        lines.append(f"    name: {json_dumps(entity.name, ensure_ascii=False)}")
        if entity.mbid:
            lines.append(f"    mbid: {entity.mbid}")
    lines.append("---")
    return "\n".join(lines)


def register(mcp: FastMCP, services: ServiceContainer) -> None:
    @mcp.tool(annotations=LOCAL_WRITE_TOOL)
    async def save_notes(
        slug: str,
        markdown: str,
        entities: list[Entity] | None = None,
    ) -> SavedNotes:
        """Write markdown liner notes into the configured playlists directory with front matter."""

        return save_markdown_notes(slug, markdown, services=services, entities=entities)
