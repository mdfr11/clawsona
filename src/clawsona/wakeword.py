"""Name addressing after local STT; no separate English keyword model needed."""

import re
import unicodedata


class WakeWordDetector:
    def __init__(self, wake_word, aliases=()):
        self.name = wake_word.strip()
        # Only a direct address at the beginning, optionally preceded by a greeting.
        # Mentioning a name in the middle of someone else's conversation is ignored.
        names = [self.name, *aliases]
        name = "(?:" + "|".join(re.escape(item) for item in names) + ")"
        self._pattern = re.compile(
            rf"^\s*(?:(?:эй|привет|здравствуй|здравствуйте|слушай|ну|пожалуйста|hey|hello|hi)[\s,!.:—–-]+){{0,3}}"
            rf"{name}(?!\w)[\s,!.:;?—–-]*",
            re.IGNORECASE,
        )

    def extract(self, transcript: str) -> str | None:
        text = unicodedata.normalize("NFKC", transcript).strip()
        match = self._pattern.match(text)
        return text[match.end() :].strip() if match else None
