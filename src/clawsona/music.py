"""Personal Yandex Music playback; credentials never enter the agent context."""

import asyncio
import os
import shutil
import signal
from urllib.parse import urlparse


class YandexMusicPlayer:
    def __init__(self, config):
        from clawsona.yandex_auth import saved_token

        self._manual_token = config.yandex_music_token
        self._token = config.yandex_music_token or saved_token()
        self._volume = config.music_volume
        self._client = None
        self._process = None
        self._track = None
        self._paused = False
        self._lock = asyncio.Lock()

    def _find_track(self, query):
        from clawsona.yandex_auth import saved_token

        current_token = self._manual_token or saved_token()
        if current_token != self._token:
            self._token, self._client = current_token, None
        if not self._token:
            raise ValueError(
                "Яндекс Музыка не подключена. Выполните clawsona yandex-login"
            )
        from yandex_music import Client

        if self._client is None:
            self._client = Client(self._token).init()
        if not self._client.me.plus.has_plus:
            raise ValueError(
                "Для полного воспроизведения нужна активная подписка Яндекс Плюс"
            )
        if query:
            search = self._client.search(query, type_="track")
            tracks = search.tracks.results if search.tracks else []
        else:
            likes = self._client.users_likes_tracks()
            tracks = [likes[0].fetch_track()] if likes else []
        if not tracks:
            raise ValueError("Трек не найден в Яндекс Музыке")
        track = next((t for t in tracks if t.available), None)
        if track is None:
            raise ValueError("Найденные треки недоступны для этого аккаунта")
        variants = [i for i in track.get_download_info() if i.codec == "mp3"]
        if not variants:
            raise ValueError(
                "Полное воспроизведение трека недоступно; проверьте подписку Яндекс Плюс"
            )
        info = max(variants, key=lambda item: item.bitrate_in_kbps)
        url = info.get_direct_link()
        parsed = urlparse(url)
        # Only the library's Yandex CDN links, never arbitrary model-provided URLs.
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or not (
                parsed.hostname.endswith(".yandex.net")
                or parsed.hostname.endswith(".yandex.ru")
            )
        ):
            raise ValueError("Неожиданный адрес музыкального потока")
        return {
            "title": track.title,
            "artist": ", ".join(a.name for a in track.artists),
            "id": str(track.id),
        }, url

    async def command(self, action: str, query: str = "") -> dict:
        async with self._lock:
            if action == "play":
                if not isinstance(query, str) or len(query.strip()) > 300:
                    raise ValueError("Укажите исполнителя или название трека")
                binary = shutil.which("ffplay")
                if not binary:
                    raise ValueError("Для музыки установите ffmpeg с ffplay")
                track, url = await asyncio.to_thread(self._find_track, query.strip())
                await self._stop()
                self._process = await asyncio.create_subprocess_exec(
                    binary,
                    "-nodisp",
                    "-autoexit",
                    "-loglevel",
                    "quiet",
                    "-volume",
                    str(self._volume),
                    url,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.sleep(0.3)
                if self._process.returncode is not None:
                    raise RuntimeError("Плеер не смог открыть музыкальный поток")
                self._track, self._paused = track, False
            elif action == "stop":
                await self._stop()
            elif action in {"pause", "resume"}:
                if self._process is None or self._process.returncode is not None:
                    return {"status": "stopped", "message": "Музыка сейчас не играет"}
                sig = signal.SIGSTOP if action == "pause" else signal.SIGCONT
                self._process.send_signal(sig)
                self._paused = action == "pause"
            elif action != "status":
                raise ValueError("Неизвестная команда плеера")
            playing = self._process is not None and self._process.returncode is None
            return {
                "status": ("paused" if self._paused else "playing")
                if playing
                else "stopped",
                "track": self._track if playing else None,
            }

    async def _stop(self):
        process, self._process = self._process, None
        self._paused, self._track = False, None
        if process is not None and process.returncode is None:
            try:
                if os.name == "posix":
                    process.send_signal(signal.SIGCONT)
                process.terminate()
            except ProcessLookupError:
                await process.wait()
                return
            try:
                await asyncio.wait_for(process.wait(), 3)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def close(self):
        async with self._lock:
            await self._stop()
