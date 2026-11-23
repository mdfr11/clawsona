import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from clawsona.config import Settings
from clawsona.music import YandexMusicPlayer

pytest.importorskip("yandex_music", reason="Install the music extra")


def test_missing_account_does_not_claim_playback(mocker):
    mocker.patch("clawsona.yandex_auth.saved_token", return_value="")
    player = YandexMusicPlayer(Settings(_env_file=None, yandex_music_token=""))
    with pytest.raises(ValueError, match="yandex-login"):
        player._find_track("test")


def test_subscription_checked_on_every_attempt(mocker):
    mocker.patch("clawsona.yandex_auth.saved_token", return_value="")
    player = YandexMusicPlayer(
        Settings(_env_file=None, yandex_music_token="valid-test")
    )
    client = MagicMock()
    client.me.plus.has_plus = False
    mocker.patch("yandex_music.Client", return_value=client)
    client.init.return_value = client
    for _ in range(2):
        with pytest.raises(ValueError, match="Яндекс Плюс"):
            player._find_track("test")
    client.search.assert_not_called()


def test_signed_url_from_unexpected_host_is_not_played(mocker):
    mocker.patch("clawsona.yandex_auth.saved_token", return_value="")
    player = YandexMusicPlayer(
        Settings(_env_file=None, yandex_music_token="valid-test")
    )
    client = MagicMock()
    client.me.plus.has_plus = True
    variant = MagicMock(codec="mp3", bitrate_in_kbps=192)
    variant.get_direct_link.return_value = "https://example.com/track.mp3"
    track = MagicMock(available=True)
    track.get_download_info.return_value = [variant]
    client.search.return_value.tracks.results = [track]
    player._client = client
    with pytest.raises(ValueError, match="адрес"):
        player._find_track("test")


def playing_player(mocker):
    mocker.patch("clawsona.yandex_auth.saved_token", return_value="")
    player = YandexMusicPlayer(Settings(_env_file=None))
    playback = MagicMock(
        active=AsyncMock(return_value=True),
        set_paused=AsyncMock(),
        set_volume=AsyncMock(),
        stop=AsyncMock(),
        close=AsyncMock(),
        load=AsyncMock(),
    )
    player._playback = playback
    player._track = {"title": "test", "id": "1"}
    return player, playback


@pytest.mark.asyncio
async def test_nested_speech_keeps_music_paused_for_the_whole_reply(mocker):
    player, playback = playing_player(mocker)
    async with player.pause_for_speech():
        async with player.pause_for_speech():
            status = await player.command("status")
            assert status["status"] == "paused"
            assert status["paused_for_speech"] is True
        assert all(args == call(True) for args in playback.set_paused.call_args_list)
    assert playback.set_paused.call_args_list[-1] == call(False)


@pytest.mark.asyncio
async def test_user_pause_during_speech_is_not_undone(mocker):
    player, playback = playing_player(mocker)
    async with player.pause_for_speech():
        await player.command("pause")
    assert all(args == call(True) for args in playback.set_paused.call_args_list)
    assert (await player.command("status"))["status"] == "paused"
    await player.command("resume")
    playback.set_paused.assert_awaited_with(False)


@pytest.mark.asyncio
async def test_resume_during_speech_waits_for_the_end_of_tts(mocker):
    player, playback = playing_player(mocker)
    await player.command("pause")
    async with player.pause_for_speech():
        await player.command("resume")
        assert all(args == call(True) for args in playback.set_paused.call_args_list)
    playback.set_paused.assert_awaited_with(False)


@pytest.mark.asyncio
async def test_user_stop_during_speech_does_not_restart_the_track(mocker):
    player, playback = playing_player(mocker)
    async with player.pause_for_speech():
        await player.command("stop")
        calls = list(playback.set_paused.call_args_list)
    assert playback.set_paused.call_args_list == calls
    assert (await player.command("status"))["status"] == "stopped"
    playback.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_speech_releases_the_music_pause(mocker):
    player, playback = playing_player(mocker)
    with pytest.raises(asyncio.CancelledError):
        async with player.pause_for_speech():
            raise asyncio.CancelledError
    playback.set_paused.assert_awaited_with(False)
    assert player._speech_depth == 0


@pytest.mark.asyncio
async def test_cancel_during_pause_entry_does_not_leak_a_pause(mocker):
    player, playback = playing_player(mocker)
    playback.set_paused.side_effect = [asyncio.CancelledError(), None]
    with pytest.raises(asyncio.CancelledError):
        async with player.pause_for_speech():
            pytest.fail("Cancelled context must not start speech")
    assert player._speech_depth == 0
    playback.set_paused.assert_awaited_with(False)


@pytest.mark.asyncio
async def test_track_started_during_speech_stays_paused(mocker):
    player, playback = playing_player(mocker)
    player._track = None
    prepared = ([object()], 0, {"title": "test"}, "https://music.yandex.net/test")
    mocker.patch.object(player, "_prepare_play", return_value=prepared)
    async with player.pause_for_speech():
        await player.command("play", "test")
        playback.load.assert_awaited_once_with(prepared[-1], volume=50, paused=True)
    playback.set_paused.assert_awaited_with(False)


@pytest.mark.asyncio
async def test_volume_changes_do_not_reload_track_or_unpause_speech(mocker):
    player, playback = playing_player(mocker)
    async with player.pause_for_speech():
        assert (await player.command("volume_up"))["volume"] == 60
        assert (await player.command("volume_down", step=20))["volume"] == 40
        assert (await player.command("set_volume", volume=75))["volume"] == 75
        playback.set_volume.assert_awaited_with(75)
        playback.load.assert_not_awaited()
        assert all(args == call(True) for args in playback.set_paused.call_args_list)


@pytest.mark.asyncio
async def test_volume_is_bounded_and_invalid_values_rejected(mocker):
    player, playback = playing_player(mocker)
    assert (await player.command("volume_up", step=100))["volume"] == 100
    assert (await player.command("volume_down", step=100))["volume"] == 0
    for value in (-1, 101, True, "50"):
        with pytest.raises(ValueError):
            await player.command("set_volume", volume=value)
    with pytest.raises(ValueError):
        await player.command("volume_up", step=0)
    assert player._volume == 0


@pytest.mark.asyncio
async def test_next_advances_queue_but_failed_next_keeps_current_track(mocker):
    player, playback = playing_player(mocker)
    queue = [object(), object()]
    player._queue, player._queue_index = queue, 0
    selected = {"title": "next", "id": "2"}
    choose = mocker.patch.object(
        player,
        "_select_track",
        return_value=(1, selected, "https://music.yandex.net/next"),
    )
    result = await player.command("next")
    choose.assert_called_once_with(queue, 1)
    assert result["track"]["id"] == "2"
    assert result["queue_position"] == 2
    choose.side_effect = ValueError("Очередь закончилась")
    with pytest.raises(ValueError):
        await player.command("next")
    assert player._track == selected
    assert playback.load.await_count == 1


@pytest.mark.asyncio
async def test_next_without_queue_does_not_claim_playback(mocker):
    player, playback = playing_player(mocker)
    with pytest.raises(ValueError, match="очередь"):
        await player.command("next")
    playback.load.assert_not_awaited()
