import pytest

from clawsona.music_commands import MusicCommand, parse_music_command


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Громче!", MusicCommand("volume_up")),
        ("Сделай музыку громче на двадцать", MusicCommand("volume_up", step=20)),
        ("потише", MusicCommand("volume_down")),
        ("сделай тише на 15 процентов", MusicCommand("volume_down", step=15)),
        ("Громкость музыки тридцать процентов", MusicCommand("set_volume", volume=30)),
        ("установи громкость на семьдесят пять", MusicCommand("set_volume", volume=75)),
        ("громкость 0%", MusicCommand("set_volume", volume=0)),
        ("громкость -5", MusicCommand("set_volume", volume=-5)),
        ("Стоп", MusicCommand("pause")),
        ("продолжить", MusicCommand("resume")),
        ("следующий трек", MusicCommand("next")),
        ("выключи музыку", MusicCommand("stop")),
        ("Louder by twenty", MusicCommand("volume_up", step=20)),
        ("quieter by 15 percent", MusicCommand("volume_down", step=15)),
        ("set volume to seventy-five percent", MusicCommand("set_volume", volume=75)),
        ("stop the music", MusicCommand("pause")),
        ("resume the music", MusicCommand("resume")),
        ("skip this song", MusicCommand("next")),
    ],
)
def test_explicit_playback_phrases(text, expected):
    assert parse_music_command(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Объясни, как сделать музыку тише",
        "Почему следующий трек не похож на прошлый?",
        "Поговорим про громкость музыки",
        "Громче начинается припев этой песни",
        "Стоп — это название моего проекта",
        "Включи джаз",
        "Teach me Spanish",
        "",
    ],
)
def test_free_form_requests_are_left_for_the_agent(text):
    assert parse_music_command(text) is None
