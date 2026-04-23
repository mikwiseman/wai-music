"""Supported language helpers."""

from __future__ import annotations

SUPPORTED_LANGUAGES = frozenset({"en", "ru"})


def validate_language(language: str | None, *, default: str = "en") -> str:
    candidate = (language or default).strip().lower()
    if candidate not in SUPPORTED_LANGUAGES:
        supported = ", ".join(sorted(SUPPORTED_LANGUAGES))
        raise ValueError(f"unsupported language: {candidate!r}; expected one of: {supported}")
    return candidate
