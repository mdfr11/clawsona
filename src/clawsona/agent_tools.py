"""Bounded network tools used by the dedicated OpenClaw agent."""

import aiohttp

from clawsona.timing import stage_timer

WEATHER_CODES = {
    0: "ясно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь",
    51: "слабая морось",
    53: "морось",
    55: "сильная морось",
    56: "переохлаждённая морось",
    57: "сильная переохлаждённая морось",
    61: "небольшой дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "ледяной дождь",
    67: "сильный ледяной дождь",
    71: "небольшой снег",
    73: "снег",
    75: "сильный снег",
    77: "снежная крупа",
    80: "небольшой ливень",
    81: "ливень",
    82: "сильный ливень",
    85: "снежный ливень",
    86: "сильный снежный ливень",
    95: "гроза",
    96: "гроза с градом",
    99: "сильная гроза с градом",
}


async def weather(city: str, day_offset: int = 0, *, session=None) -> dict:
    if not isinstance(city, str) or not 2 <= len(city.strip()) <= 120:
        raise ValueError("Укажите город")
    if type(day_offset) is not int or not 0 <= day_offset <= 7:
        raise ValueError("Прогноз доступен на сегодня и семь следующих дней")
    own_session = session is None
    session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25))
    try:
        with stage_timer("weather_geocode"):
            async with session.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city.strip(), "count": 3, "language": "ru"},
            ) as response:
                response.raise_for_status()
                places = (await response.json()).get("results") or []
        if not places:
            return {"error": "Город не найден. Уточните название или регион."}
        # Geocoding also returns stations/administrative areas named like a city.
        settlements = [
            p
            for p in places
            if p.get("feature_code", "").startswith("PPL")
            and p.get("feature_code") != "PPLX"
        ]
        places = settlements or places
        exact = [
            p for p in places if p.get("name", "").casefold() == city.strip().casefold()
        ]
        if len(exact) > 1:
            return {
                "needs_clarification": [
                    dict(
                        name=p["name"], region=p.get("admin1"), country=p.get("country")
                    )
                    for p in exact
                ]
            }
        place = (exact or places)[0]
        params = {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "forecast_days": day_offset + 1,
            "timezone": "auto",
            "wind_speed_unit": "ms",
        }
        with stage_timer("weather_forecast"):
            async with session.get(
                "https://api.open-meteo.com/v1/forecast", params=params
            ) as response:
                response.raise_for_status()
                data = await response.json()
        current, daily = data["current"], data["daily"]
        return {
            "source": "Open-Meteo",
            "city": place["name"],
            "region": place.get("admin1"),
            "country": place.get("country"),
            "timezone": data["timezone"],
            "current": {
                "time": current["time"],
                "temperature_c": current["temperature_2m"],
                "feels_like_c": current["apparent_temperature"],
                "conditions": WEATHER_CODES.get(current["weather_code"], "неизвестно"),
                "wind_m_s": current["wind_speed_10m"],
            },
            "forecast": {
                "date": daily["time"][day_offset],
                "min_c": daily["temperature_2m_min"][day_offset],
                "max_c": daily["temperature_2m_max"][day_offset],
                "rain_probability_percent": daily["precipitation_probability_max"][
                    day_offset
                ],
                "conditions": WEATHER_CODES.get(
                    daily["weather_code"][day_offset], "неизвестно"
                ),
            },
        }
    finally:
        if own_session:
            await session.close()


async def web_search(query: str, api_key: str) -> dict:
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 128:
        raise ValueError("Поисковый запрос должен содержать от одного до 128 символов")
    if not api_key:
        raise ValueError("Для поиска нужен DEEPSEEK_API_KEY")
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30)
    ) as session:
        with stage_timer("search_request"):
            async with session.post(
                "https://api.deepseek.com/v1/tools/search",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"query": query.strip()},
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"Поиск DeepSeek HTTP {response.status}")
                result = await response.json()
    return {"source": "DeepSeek Search", "untrusted_web_data": result}
