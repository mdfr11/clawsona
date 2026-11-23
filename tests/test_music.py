from unittest.mock import MagicMock

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
