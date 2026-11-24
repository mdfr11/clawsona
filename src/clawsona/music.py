"""Personal Yandex Music playback; credentials never enter the agent context."""

import asyncio
import logging
from contextlib import asynccontextmanager
from itertools import islice
from urllib.parse import urlparse

from clawsona.music_playback import MpvPlayback, PlaybackError
from clawsona.timing import stage_timer

logger = logging.getLogger(__name__)


class MusicControlError(ValueError):
    """A public, credential-free explanation for a rejected playback action."""


class YandexMusicPlayer:
    def __init__(self, config):
        from clawsona.yandex_auth import saved_token

        self._manual_token = config.yandex_music_token
        self._token = config.yandex_music_token or saved_token()
        self._volume = config.music_volume
        self._effective_volume = float(self._volume)
        self._speech_mode = config.music_speech_mode
        self._duck_ratio = config.music_duck_ratio
        self._fade_duration = config.music_fade_duration_ms / 1000
        self._auto_next = config.music_auto_next
        self._auto_task = None
        self._closing = False
        self._auto_wakeup = asyncio.Event()
        self._auto_wakeup.set()
        self._client = None
        self._track = None
        self._queue = []
        self._queue_index = -1
        self._queue_kind = None
        self._queue_artist = None
        self._paused = False
        self._speech_depth = 0
        self._lock = asyncio.Lock()
        self._playback = MpvPlayback()

    @property
    def has_playback_context(self):
        return self._track is not None

    @property
    def is_audible(self):
        # Cached playback intent; no provider or IPC round trip in activation.
        # The EOF/process observer clears the track when playback finishes.
        return bool(
            self._track is not None
            and self._playback.running
            and not self._paused
            and not (self._speech_depth and self._speech_mode == "pause")
            and self._effective_volume > 0
        )

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
            with stage_timer("music_stream_resolve"):
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
        with stage_timer("music_search", source="search" if query else "likes"):
            if query:
                search = client.search(query, type_="track")
                queue = list(islice(search.tracks.results, 50)) if search.tracks else []
            else:
                queue = list(islice(client.users_likes_tracks(), 50))
        if not queue:
            raise MusicControlError("Трек не найден в Яндекс Музыке")
        return queue, *self._select_track(queue, 0)

    def _prepare_artist(self, query):
        client = self._authenticated_client()
        with stage_timer("music_artist_lookup"):
            search = client.search(query, type_="artist")

        def normalize(name):
            return " ".join(name.casefold().replace("ё", "е").split())

        artists = (search.artists.results or []) if search and search.artists else []
        artist = next(
            (
                item
                for item in islice(artists, 20)
                if normalize(item.name) == normalize(query)
            ),
            None,
        )
        if artist is None:
            raise MusicControlError(
                "Исполнитель с таким именем не найден. Уточните название."
            )
        with stage_timer("music_artist_catalog"):
            page = artist.get_tracks(page=0, page_size=50)
        queue, seen = [], set()
        for track in islice((page.tracks or []) if page else [], 50):
            if not track or not track.id:
                continue
            track_id = str(track.id)
            if track_id in seen or not any(
                str(a.id) == str(artist.id) for a in (track.artists or [])
            ):
                continue
            seen.add(track_id)
            queue.append(track)
        if not queue:
            raise MusicControlError("У исполнителя нет доступных треков")
        return (queue, *self._select_track(queue, 0)), artist.name

    def _find_track(self, query):
        _, _, track, url = self._prepare_play(query)
        return track, url

    async def _load(self, queue, index, track, url):
        try:
            with stage_timer("music_load", queue_position=index + 1):
                await self._playback.load(
                    url,
                    volume=self._target_volume(),
                    paused=self._speech_depth > 0 and self._speech_mode == "pause",
                )
        except BaseException:
            self._track = None
            raise
        self._queue, self._queue_index = queue, index
        self._track, self._paused = track, False
        self._effective_volume = self._target_volume()
        self._auto_wakeup.set()
        self._ensure_auto_next()

    def _ensure_auto_next(self):
        if (
            self._auto_next
            and self._track is not None
            and not self._closing
            and (self._auto_task is None or self._auto_task.done())
        ):
            self._auto_task = asyncio.create_task(self._advance_loop())
            self._auto_task.add_done_callback(self._auto_finished)

    def _auto_finished(self, task):
        if self._auto_task is task:
            self._auto_task = None
        if not task.cancelled() and task.exception() is not None:
            logger.warning(
                "Наблюдение за музыкальной очередью остановлено из-за ошибки"
            )
            return
        self._ensure_auto_next()

    async def _advance_loop(self):
        while True:
            entry_id, reason = await self._playback.next_end()
            if reason == "shutdown":
                async with self._lock:
                    if entry_id == self._playback.entry_id:
                        self._track = None
                continue
            if reason != "eof":
                if reason in {"error", "quit"}:
                    async with self._lock:
                        if entry_id == self._playback.entry_id:
                            self._track = None
                            logger.warning("Воспроизведение музыки прервано")
                continue
            async with self._lock:
                if (
                    self._closing
                    or self._track is None
                    or entry_id != self._playback.entry_id
                ):
                    continue
                queue, start = self._queue, self._queue_index + 1
            try:
                # Resolve outside the control lock so stop/pause can still run
                # while the provider is responding. Recheck identity afterwards.
                prepared = (
                    await asyncio.to_thread(self._select_track, queue, start)
                    if start < len(queue)
                    else None
                )
                while True:
                    await self._auto_wakeup.wait()
                    async with self._lock:
                        if (
                            self._closing
                            or self._track is None
                            or entry_id != self._playback.entry_id
                        ):
                            break
                        if self._paused:
                            self._auto_wakeup.clear()
                            continue
                        if prepared is None:
                            await self._playback.stop()
                            self._track = None
                            logger.info("Очередь музыки завершена")
                        else:
                            async with asyncio.timeout(30):
                                await self._load(queue, *prepared)
                            logger.info(
                                "Автоматический переход к треку %d из %d",
                                self._queue_index + 1,
                                len(queue),
                            )
                        break
            except asyncio.CancelledError:
                raise
            except Exception:
                async with self._lock:
                    if entry_id == self._playback.entry_id:
                        await self._playback.close()
                        self._track = None
                logger.warning("Не удалось автоматически продолжить очередь музыки")
                return

    def _target_volume(self):
        if self._speech_depth and self._speech_mode == "duck":
            return self._volume * self._duck_ratio
        return float(self._volume)

    async def _apply_volume(self, target, *, smooth=False):
        if target == self._effective_volume:
            return
        start = self._effective_volume
        steps = (
            max(1, min(10, round(self._fade_duration / 0.04)))
            if smooth and self._fade_duration
            else 1
        )
        for index in range(1, steps + 1):
            value = start + (target - start) * index / steps
            previous = self._effective_volume
            # A cancelled IPC request may already have applied its value. Keep
            # that target so the speech context will explicitly restore volume.
            self._effective_volume = value
            try:
                await self._playback.set_volume(value)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._effective_volume = previous
                raise
            if steps > 1:
                await asyncio.sleep(self._fade_duration / steps)

    async def command(
        self, action: str, query: str = "", *, volume=None, step=10
    ) -> dict:
        async with self._lock:
            if action in {"play", "play_artist"}:
                if not isinstance(query, str) or len(query.strip()) > 300:
                    raise MusicControlError("Укажите исполнителя или название трека")
                query = query.strip()
                if action == "play_artist":
                    if not query:
                        raise MusicControlError("Укажите имя исполнителя")
                    prepared, artist = await asyncio.to_thread(
                        self._prepare_artist, query
                    )
                else:
                    prepared = await asyncio.to_thread(self._prepare_play, query)
                    artist = None
                await self._load(*prepared)
                self._queue_kind = (
                    "artist" if artist else "search" if query else "likes"
                )
                self._queue_artist = artist
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
                self._auto_wakeup.set()
            elif action in {"pause", "resume"}:
                if self._track is not None:
                    self._paused = action == "pause"
                    await self._sync_pause()
                    self._auto_wakeup.set()
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
                await self._apply_volume(
                    desired * self._duck_ratio
                    if self._speech_depth and self._speech_mode == "duck"
                    else desired
                )
                self._volume = desired
            elif action != "status":
                raise MusicControlError("Неизвестная команда плеера")
            playing = self._track is not None and await self._playback.active()
            return {
                "status": (
                    "paused"
                    if self._paused
                    or (self._speech_depth and self._speech_mode == "pause")
                    else "playing"
                )
                if playing
                else "stopped",
                "track": self._track if playing else None,
                "volume": self._volume,
                "paused_for_speech": bool(
                    playing and self._speech_depth and self._speech_mode == "pause"
                ),
                "ducked_for_speech": bool(
                    playing
                    and self._speech_depth
                    and self._speech_mode == "duck"
                    and self._duck_ratio < 1
                ),
                "effective_volume": self._effective_volume if playing else 0,
                "queue_position": self._queue_index + 1 if self._queue else 0,
                "queue_length": len(self._queue),
                "queue_kind": self._queue_kind,
                "queue_artist": self._queue_artist,
                "has_playback_context": self.has_playback_context,
            }

    async def _sync_pause(self):
        if self._track is not None:
            try:
                await self._playback.set_paused(
                    self._paused
                    or (self._speech_depth > 0 and self._speech_mode == "pause")
                )
                await self._apply_volume(self._target_volume(), smooth=True)
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
                    logger.info(
                        "Музыка на время озвучки: %s",
                        "приглушение" if self._speech_mode == "duck" else "пауза",
                    )
            yield
        finally:
            if entered:
                async with self._lock:
                    self._speech_depth -= 1
                    await self._sync_pause()

    async def close(self):
        self._closing = True
        task, self._auto_task = self._auto_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self._lock:
            self._track = None
            await self._playback.close()
