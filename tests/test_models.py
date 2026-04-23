from wai_music.models import DailyPick, Entity, EntityType, Fact, PlaylistRef, SavedNotes, Story


def test_entity_schema_is_generatable() -> None:
    schema = Entity.model_json_schema()
    entity_schema = schema["$defs"]["Entity"] if "$defs" in schema else schema
    assert entity_schema["title"] == "Entity"
    assert "properties" in entity_schema


def test_story_requires_facts_or_extract() -> None:
    entity = Entity(type=EntityType.ARTIST, name="Sergei Rachmaninoff")
    story = Story(entity_ref=entity, facts=[Fact(kind="event", label="Born")], language="en")
    assert story.facts[0].label == "Born"


def test_daily_pick_and_saved_notes_serialize() -> None:
    entity = Entity(type=EntityType.SCENE, name="Detroit Techno")
    pick = DailyPick(
        entity=entity,
        mode="scene_dive",
        angle="Origins",
        rationale="Foundational scene",
    )
    payload = pick.model_dump(mode="json")
    assert payload["mode"] == "scene_dive"

    saved = SavedNotes(
        path="playlists/2026-04-23-detroit-techno.md",
        slug="detroit-techno",
        playlist_ref=PlaylistRef(backend="spotify", playlist_id="abc123"),
        entities=[entity],
    )
    assert saved.model_dump()["playlist_ref"]["backend"] == "spotify"
