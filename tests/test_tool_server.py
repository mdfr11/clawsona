from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

from clawsona.config import Settings
from clawsona.tool_server import create_tool_app, serve_tools


@pytest.mark.asyncio
async def test_voice_and_http_tools_share_the_same_music_player(
    mocker, unused_tcp_port
):
    config = Settings(
        _env_file=None,
        music_enabled=True,
        clawsona_tools_token="test",
        clawsona_tools_port=unused_tcp_port,
    )
    player = MagicMock(
        command=AsyncMock(return_value={"status": "paused"}), close=AsyncMock()
    )
    mocker.patch("clawsona.tool_server.YandexMusicPlayer", return_value=player)
    async with serve_tools(config) as shared:
        assert shared is player
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{unused_tcp_port}/music",
                headers={"Authorization": "Bearer test"},
                json={"action": "pause"},
            ) as response:
                assert response.status == 200
                assert (await response.json())["status"] == "paused"
        player.command.assert_awaited_once_with("pause", "")
    player.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_tools_reject_unauthorized_calls_and_redact_credentials():
    config = Settings(
        _env_file=None,
        clawsona_tools_token="server-secret",
        music_enabled=True,
        yandex_music_token="yandex-secret",
    )
    player = MagicMock()
    player._token = "yandex-secret"
    player.close = AsyncMock()
    player.command = AsyncMock(side_effect=RuntimeError("yandex-secret failed"))
    async with TestServer(create_tool_app(config, player)) as server:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                server.make_url("/music"), json={"action": "play"}
            ) as response:
                assert response.status == 401
            player.command.assert_not_awaited()
            async with session.post(
                server.make_url("/music"),
                headers={"Authorization": "Bearer server-secret"},
                json={"action": "play"},
            ) as response:
                assert response.status == 400
                result = await response.json()
                assert "yandex-secret" not in str(result)
                assert "[redacted]" in result["error"]
    player.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_music_commands_reach_player_without_shell(mocker, caplog):
    caplog.set_level("INFO", logger="clawsona.timing")
    config = Settings(_env_file=None, clawsona_tools_token="test", music_enabled=True)
    player = MagicMock(
        command=AsyncMock(return_value={"status": "paused"}), close=AsyncMock()
    )
    async with TestServer(create_tool_app(config, player)) as server:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                server.make_url("/music"),
                headers={"Authorization": "Bearer test"},
                json={"action": "pause"},
            ) as response:
                assert await response.json() == {"status": "paused"}
    player.command.assert_awaited_once_with("pause", "")
    event = next(r.timing for r in caplog.records if hasattr(r, "timing"))
    assert event["stage"] == "tool"
    assert event["operation"] == "music"
    assert event["status"] == "ok"
    assert event["tool_call"]
