"""Personal Yandex Music playback; credentials never enter the agent context."""

import asyncio
import logging
from contextlib import asynccontextmanager
from itertools import islice
from urllib.parse import urlparse

from clawsona.music_playback import MpvPlayback, PlaybackError

logger = logging.getLogger(__name__)


class MusicControlError(ValueError):
    """A public, credential-free explanation for a rejected playback action."""


class YandexMusicPlayer:
    def __init__(self, config):
        from clawsona.yandex_auth import saved_token

        self._manual_token = config.yandex_music_token
        self._token = config.yandex_music_token or saved_token()
        self._volume = config.music_volume
        self._client = None
        self._track = None
        self._queue = []
        self._queue_index = -1
        self._paused = False
        self._speech_depth = 0
        self._lock = asyncio.Lock()
        self._playback = MpvPlayback()

    @property
    def has_playback_context(self):
        return self._track is not None

    def _authenticated_client(self):
        from clawsona.yandex_auth import saved_token

        token = self._manual_token or saved_token()
        if token != self._token:
            self._token, self._client = token, None
        if not self._token:
            raise MusicControlError(
                "Яндекс Музыка не подключена. Выполните clawsona yandex-login"
            )
        from yandex_music import Client

        if self._client is None:
            self._client = Client(self._token).init()
        if not self._client.me.plus.has_plus:
            raise MusicControlError(
                "Для полного воспроизведения нужна активная подписка Яндекс Плюс"
            )
        return self._client

    def _select_track(self, queue, start):
        self._authenticated_client()
        for index in range(start, len(queue)):
            item = queue[index]
            track = (
                item
                if callable(getattr(item, "get_download_info", None))
                else item.fetch_track()
            )
            if not track or not track.available:
                continue
            variants = [i for i in track.get_download_info() if i.codec == "mp3"]
            if not variants:
                continue
            url = max(variants, key=lambda i: i.bitrate_in_kbps).get_direct_link()
            parsed = urlparse(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or not (
                    parsed.hostname.endswith(".yandex.net")
                    or parsed.hostname.endswith(".yandex.ru")
                )
            ):
                raise MusicControlError("Неожиданный адрес музыкального потока")
            metadata = {
                "title": track.title,
                "artist": ", ".join(a.name for a in track.artists),
                "id": str(track.id),
            }
            return index, metadata, url
        raise MusicControlError("Доступных треков дальше нет. Включите другую музыку.")

    def _prepare_play(self, query):
        client = self._authenticated_client()
        if query:
            search = client.search(query, type_="track")
            queue = list(islice(search.tracks.results, 50)) if search.tracks else []
        else:
            queue = list(islice(client.users_likes_tracks(), 50))
        if not queue:
            raise MusicControlError("Трек не найден в Яндекс Музыке")
        return queue, *self._select_track(queue, 0)

    def _find_track(self, query):
        _, _, track, url = self._prepare_play(query)
        return track, url

    async def _load(self, queue, index, track, url):
        try:
            await self._playback.load(
                url, volume=self._volume, paused=self._speech_depth > 0
            )
        except BaseException:
            self._track = None
            raise
        self._queue, self._queue_index = queue, index
        self._track, self._paused = track, False

    async def command(
        self, action: str, query: str = "", *, volume=None, step=10
    ) -> dict:
        async with self._lock:
            if action == "play":
                if not isinstance(query, str) or len(query.strip()) > 300:
                    raise MusicControlError("Укажите исполнителя или название трека")
                prepared = await asyncio.to_thread(self._prepare_play, query.strip())
                await self._load(*prepared)
            elif action == "next":
                if not self._queue:
                    raise MusicControlError(
                        "Сначала включите музыку, чтобы создать очередь"
                    )
                prepared = await asyncio.to_thread(
                    self._select_track, self._queue, self._queue_index + 1
                )
                await self._load(self._queue, *prepared)
            elif action == "stop":
                await self._playback.stop()
                self._track, self._paused = None, False
            elif action in {"pause", "resume"}:
                if self._track is not None and await self._playback.active():
                    self._paused = action == "pause"
                    await self._sync_pause()
            elif action in {"volume_up", "volume_down", "set_volume"}:
                if action == "set_volume":
                    if type(volume) is not int or not 0 <= volume <= 100:
                        raise MusicControlError(
                            "Громкость задаётся целым числом от 0 до 100"
                        )
                    desired = volume
                else:
                    if type(step) is not int or not 1 <= step <= 100:
                        raise MusicControlError(
                            "Шаг громкости задаётся целым числом от 1 до 100"
                        )
                    desired = min(
                        100,
                        max(
                            0, self._volume + (step if action == "volume_up" else -step)
                        ),
                    )
                await self._playback.set_volume(desired)
                self._volume = desired
            elif action != "status":
                raise MusicControlError("Неизвестная команда плеера")
            playing = self._track is not None and await self._playback.active()
            return {
                "status": (
                    "paused" if self._paused or self._speech_depth else "playing"
                )
                if playing
                else "stopped",
                "track": self._track if playing else None,
                "volume": self._volume,
                "paused_for_speech": bool(playing and self._speech_depth),
                "queue_position": self._queue_index + 1 if self._queue else 0,
                "queue_length": len(self._queue),
            }

    async def _sync_pause(self):
        if self._track is not None:
            try:
                await self._playback.set_paused(self._paused or self._speech_depth > 0)
            except (PlaybackError, OSError, TimeoutError):
                logger.warning(
                    "Музыкальный плеер недоступен; останавливаю его перед озвучкой"
                )
                await self._playback.close()
                self._track = None

    @asynccontextmanager
    async def pause_for_speech(self):
        entered = False
        try:
            async with self._lock:
                self._speech_depth += 1
                entered = True
                await self._sync_pause()
                if self._track is not None and self._speech_depth == 1:
                    logger.info("Музыка на паузе на время озвучки")
            yield
        finally:
            if entered:
                async with self._lock:
                    self._speech_depth -= 1
                    await self._sync_pause()

    async def close(self):
        async with self._lock:
            self._track = None
            await self._playback.close()
