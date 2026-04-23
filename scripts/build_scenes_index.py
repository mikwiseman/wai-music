"""Validate or summarize the curated scenes index."""

from __future__ import annotations

import json
from pathlib import Path

from wai_music.data import load_scenes


def main() -> int:
    scenes = load_scenes()
    countries = sorted({country for scene in scenes.values() for country in scene.countries})
    payload = {
        "scene_count": len(scenes),
        "countries": countries,
        "keys": sorted(scenes)[:10],
    }
    output_path = Path("src/wai_music/data/scenes.index.json")
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {output_path} with {len(scenes)} scenes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
