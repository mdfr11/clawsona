"""Script-based routing for the two local speech voices; no network detector."""

import re
import unicodedata

_WORDS = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)


def speech_parts(text: str, default="ru") -> list[tuple[str, str]]:
    """Keep every character, grouping adjacent Latin/Cyrillic words by voice."""
    parts = []
    start = 0
    current = None
    for word in _WORDS.finditer(text):
        script = unicodedata.name(word.group()[0], "")
        language = (
            "ru" if "CYRILLIC" in script else "en" if "LATIN" in script else default
        )
        if current is not None and current != language:
            parts.append((current, text[start : word.start()]))
            start = word.start()
        current = language
    if text:
        parts.append((current or default, text[start:]))
    return parts
