"""Small, explicit playback controls; free-form requests still go to OpenClaw."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MusicCommand:
    action: str
    volume: int | None = None
    step: int | None = None

    def options(self):
        return {
            key: value
            for key, value in (("volume", self.volume), ("step", self.step))
            if value is not None
        }


UNITS_RU = "ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать".split()
UNITS_EN = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS_RU = "двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто".split()
TENS_EN = "twenty thirty forty fifty sixty seventy eighty ninety".split()
NUMBERS = {"нуль": 0, "сто": 100, "hundred": 100, "one hundred": 100}
for units, tens in ((UNITS_RU, TENS_RU), (UNITS_EN, TENS_EN)):
    NUMBERS.update({word: number for number, word in enumerate(units)})
    for number, word in enumerate(tens, 2):
        NUMBERS[word] = number * 10
        NUMBERS.update(
            {f"{word} {units[unit]}": number * 10 + unit for unit in range(1, 10)}
        )


def _number(text):
    if re.fullmatch(r"-?\d{1,3}", text):
        return int(text)
    return NUMBERS.get(text)


def parse_music_command(text: str) -> MusicCommand | None:
    text = text.casefold().replace("ё", "е")
    text = re.sub(r"(?<=[a-zа-я])-(?=[a-zа-я])", " ", text)
    text = re.sub(r"[^\w\s%\-]", " ", text).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^(?:пожалуйста|please) | (?:пожалуйста|please)$", "", text).strip()
    simple = {
        "pause": {
            "стоп",
            "пауза",
            "останови",
            "останови музыку",
            "поставь на паузу",
            "поставь музыку на паузу",
            "stop",
            "pause",
            "stop music",
            "stop the music",
            "pause music",
            "pause the music",
        },
        "resume": {
            "продолжить",
            "продолжи",
            "продолжи музыку",
            "возобнови музыку",
            "играй дальше",
            "resume",
            "continue",
            "continue music",
            "resume music",
            "resume the music",
        },
        "next": {
            "следующий",
            "следующая",
            "следующий трек",
            "следующая песня",
            "переключи трек",
            "переключи на следующий трек",
            "next",
            "next track",
            "next song",
            "skip",
            "skip this song",
            "skip track",
        },
        "stop": {
            "выключи музыку",
            "выключить музыку",
            "turn off music",
            "turn off the music",
        },
    }
    for action, phrases in simple.items():
        if text in phrases:
            return MusicCommand(action)
    match = re.fullmatch(
        r"(?:(?:сделай|сделать) )?(?:музыку )?(погромче|громче|потише|тише)(?: (?:на )?(.+?)(?: (?:процент(?:а|ов)?|пункт(?:а|ов)?)|%)?)?",
        text,
    )
    if not match:
        match = re.fullmatch(
            r"(?:music )?(louder|quieter|softer|volume up|volume down)(?: (?:by )?(.+?)(?: percent|%)?)?",
            text,
        )
    if match:
        action = (
            "volume_up"
            if match[1] in {"погромче", "громче", "louder", "volume up"}
            else "volume_down"
        )
        step = _number(match[2]) if match[2] else None
        if match[2] and step is None:
            return None
        return MusicCommand(action, step=step)
    match = re.fullmatch(
        r"(?:(?:сделай|поставь|установи|выставь) )?громкость(?: музыки)? (?:на )?(.+?)(?: процент(?:а|ов)?|%)?",
        text,
    )
    if not match:
        match = re.fullmatch(
            r"(?:set )?(?:music )?volume (?:to )?(.+?)(?: percent|%)?", text
        )
    if match and (value := _number(match[1])) is not None:
        return MusicCommand("set_volume", volume=value)
    return None


def music_reply(command, result, *, english=False):
    if command.action in {"volume_up", "volume_down", "set_volume"}:
        return (
            f"Music volume is {result['volume']} percent."
            if english
            else f"Громкость музыки — {result['volume']} процентов."
        )
    track = result.get("track")
    if command.action == "stop":
        return "Music is off." if english else "Музыка выключена."
    if not track:
        return (
            "No music is playing. Choose a track first."
            if english
            else "Музыка сейчас не играет. Сначала включи трек."
        )
    if command.action == "pause":
        return "Music paused." if english else "Музыка на паузе."
    if command.action == "resume":
        return "Resuming the music." if english else "Продолжаю музыку."
    return (
        f"Playing {track['artist']} — {track['title']}."
        if english
        else f"Включаю: {track['artist']} — {track['title']}."
    )
