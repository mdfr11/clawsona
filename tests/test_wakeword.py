import pytest

from clawsona.wakeword import WakeWordDetector


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("Лютик", ""),
        ("Лютик!", ""),
        (
            "лютик привет какой прогноз погоды в крымске",
            "привет какой прогноз погоды в крымске",
        ),
        ("Привет, Лютик, включи музыку", "включи музыку"),
        ("Эй, Лютик. Как дела?", "Как дела?"),
        ("Лютики растут на лугу", None),
        ("Мы говорили про Лютика", None),
        ("Мой друг Лютик рассказал историю", None),
        ("Привет, как дела?", None),
        ("Lyutik, hello!", "hello!"),
        ("Hello, Lutik. How are you?", "How are you?"),
        ("Lyutik", ""),
        ("Lyutiks", None),
        ("Lyudik, hello", None),
        ("Людик, привет", None),
    ],
)
def test_direct_name_addressing(phrase, expected):
    assert WakeWordDetector("Лютик", ["Lyutik", "Lutik"]).extract(phrase) == expected


@pytest.mark.parametrize(
    "name,aliases,phrase,expected",
    [
        ("Мира", ["Mira"], "Мира, привет", "привет"),
        ("Мира", ["Mira"], "Hello, Mira. How are you?", "How are you?"),
        ("Мира", ["Mira"], "Лютик, привет", None),
        ("Мира", ["Mira"], "Lyutik, hello", None),
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
