import asyncio
import signal
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
    player._process = MagicMock(returncode=None, wait=AsyncMock(return_value=0))
    return player, player._process


@pytest.mark.asyncio
async def test_nested_speech_pauses_once_and_restores_after_the_whole_reply(mocker):
    player, process = playing_player(mocker)
    async with player.pause_for_speech():
        async with player.pause_for_speech():
            status = await player.command("status")
            assert status["status"] == "paused"
            assert status["paused_for_speech"] is True
        process.send_signal.assert_called_once_with(signal.SIGSTOP)
    assert process.send_signal.call_args_list == [
        call(signal.SIGSTOP),
        call(signal.SIGCONT),
    ]


@pytest.mark.asyncio
async def test_user_pause_during_speech_is_not_undone(mocker):
    player, process = playing_player(mocker)
    async with player.pause_for_speech():
        await player.command("pause")
    process.send_signal.assert_called_once_with(signal.SIGSTOP)
    assert (await player.command("status"))["status"] == "paused"
    await player.command("resume")
    assert process.send_signal.call_args_list[-1] == call(signal.SIGCONT)


@pytest.mark.asyncio
async def test_resume_during_speech_waits_for_the_end_of_tts(mocker):
    player, process = playing_player(mocker)
    await player.command("pause")
    async with player.pause_for_speech():
        await player.command("resume")
        process.send_signal.assert_called_once_with(signal.SIGSTOP)
    assert process.send_signal.call_args_list[-1] == call(signal.SIGCONT)


@pytest.mark.asyncio
async def test_user_stop_during_speech_does_not_restart_the_track(mocker):
    player, process = playing_player(mocker)
    async with player.pause_for_speech():
        await player.command("stop")
        calls = list(process.send_signal.call_args_list)
    assert process.send_signal.call_args_list == calls
    assert (await player.command("status"))["status"] == "stopped"
    process.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_cancelled_speech_releases_the_music_pause(mocker):
    player, process = playing_player(mocker)
    with pytest.raises(asyncio.CancelledError):
        async with player.pause_for_speech():
            raise asyncio.CancelledError
    assert process.send_signal.call_args_list[-1] == call(signal.SIGCONT)
    assert player._speech_depth == 0


@pytest.mark.asyncio
async def test_finished_track_is_not_resumed_after_speech(mocker):
    player, process = playing_player(mocker)
    async with player.pause_for_speech():
        process.returncode = 0
    process.send_signal.assert_called_once_with(signal.SIGSTOP)


@pytest.mark.asyncio
async def test_track_started_during_speech_is_paused_until_reply_ends(mocker):
    player, process = playing_player(mocker)
    player._process = None
    mocker.patch.object(
        player,
        "_find_track",
        return_value=({"title": "test"}, "https://music.yandex.net/test"),
    )
    mocker.patch("clawsona.music.shutil.which", return_value="ffplay")
    mocker.patch(
        "clawsona.music.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=process,
    )
    mocker.patch("clawsona.music.asyncio.sleep", new_callable=AsyncMock)
    async with player.pause_for_speech():
        await player.command("play", "test")
        process.send_signal.assert_called_once_with(signal.SIGSTOP)
    assert process.send_signal.call_args_list[-1] == call(signal.SIGCONT)
