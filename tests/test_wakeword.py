import pytest

from clawsona.wakeword import WakeWordDetector


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("Мира", ""),
        ("Мира!", ""),
        (
            "мира привет какой прогноз погоды в крымске",
            "привет какой прогноз погоды в крымске",
        ),
        ("Привет, Мира, включи музыку", "включи музыку"),
        ("Эй, Мира. Как дела?", "Как дела?"),
        ("Миражи бывают в пустыне", None),
        ("Мы говорили про Миру", None),
        ("Мой друг Мира рассказал историю", None),
        ("Привет, как дела?", None),
        ("Mira, hello!", "hello!"),
        ("Hello, Meera. How are you?", "How are you?"),
        ("Mira", ""),
        ("Miras", None),
        ("Nira, hello", None),
        ("Нира, привет", None),
    ],
)
def test_direct_name_addressing(phrase, expected):
    assert WakeWordDetector("Мира", ["Mira", "Meera"]).extract(phrase) == expected


@pytest.mark.parametrize(
    "name,aliases,phrase,expected",
    [
        ("Мира", ["Mira"], "Мира, привет", "привет"),
        ("Мира", ["Mira"], "Hello, Mira. How are you?", "How are you?"),
        ("Мира", ["Mira"], "Атлас, привет", None),
        ("Мира", ["Mira"], "Atlas, hello", None),
        ("Мира", [], "Mira, hello", None),
        ("R2-D2", [], "R2-D2, hello", "hello"),
        ("Жан Люк", [], "Привет, Жан Люк! Как дела?", "Как дела?"),
        ("Атлас", [], "Атласы бывают разные", None),
        ("Мира", [], "Мы говорили про Мира", None),
        ("C++", [], "C++, привет", "привет"),
    ],
)
def test_any_configured_name_and_only_explicit_aliases(name, aliases, phrase, expected):
    assert WakeWordDetector(name, aliases).extract(phrase) == expected
