from unittest.mock import AsyncMock, MagicMock

import pytest

from clawsona.agent_tools import weather


def response(data):
    value = MagicMock()
    value.json = AsyncMock(return_value=data)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=value)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


@pytest.mark.asyncio
async def test_city_part_does_not_make_real_city_ambiguous():
    session = MagicMock()
    session.get.side_effect = [
        response(
            {
                "results": [
                    {
                        "name": "Крымск",
                        "feature_code": "PPLA2",
                        "latitude": 44.926,
                        "longitude": 37.99,
                        "admin1": "Краснодарский край",
                    },
                    {
                        "name": "Крымск",
                        "feature_code": "PPLX",
                        "latitude": 44.931,
                        "longitude": 37.992,
                        "admin1": "Краснодарский край",
                    },
                ]
            }
        ),
        response(
            {
                "timezone": "Europe/Moscow",
                "current": {
                    "time": "2026-11-10T17:00",
                    "temperature_2m": 7.9,
                    "apparent_temperature": 5.9,
                    "weather_code": 3,
                    "wind_speed_10m": 1,
                },
                "daily": {
                    "time": ["2026-11-10"],
                    "temperature_2m_min": [2.1],
                    "temperature_2m_max": [9.3],
                    "precipitation_probability_max": [8],
                    "weather_code": [45],
                },
            }
        ),
    ]
    result = await weather("Крымск", session=session)
    assert result["current"]["temperature_c"] == 7.9
    assert result["city"] == "Крымск"
    assert session.get.call_count == 2


@pytest.mark.asyncio
async def test_two_actual_cities_require_clarification():
    session = MagicMock()
    session.get.return_value = response(
        {
            "results": [
                {
                    "name": "Springfield",
                    "feature_code": "PPL",
                    "admin1": "Illinois",
                    "country": "US",
                },
                {
                    "name": "Springfield",
                    "feature_code": "PPL",
                    "admin1": "Missouri",
                    "country": "US",
                },
            ]
        }
    )
    result = await weather("Springfield", session=session)
    assert len(result["needs_clarification"]) == 2
    session.get.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "city,day", [("", 0), ("Крымск", True), ("Крымск", -1), ("Крымск", 8)]
)
async def test_invalid_weather_input_never_fetches(city, day):
    session = MagicMock()
    with pytest.raises(ValueError):
        await weather(city, day, session=session)
    session.get.assert_not_called()
