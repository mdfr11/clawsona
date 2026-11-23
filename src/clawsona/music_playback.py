"""Local mpv playback through a private Unix socket, without another Python SDK."""

import asyncio
import json
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path


class PlaybackError(RuntimeError):
    pass


class MpvPlayback:
    def __init__(self, *, extra_args=()):
        self._process = None
        self._directory = None
        self._socket = None
        self._extra_args = tuple(extra_args)

    @property
    def running(self):
        return self._process is not None and self._process.returncode is None

    async def _start(self):
        if self.running:
            return
        await self.close()
        binary = shutil.which("mpv")
        if not binary:
            raise PlaybackError(
                "Для музыки установите mpv: brew install mpv или sudo apt install mpv"
            )
        # Short path fits Unix socket limits on macOS. The directory is mode 0700;
        # the powerful mpv IPC interface is never exposed to the network or model.
        self._directory = tempfile.TemporaryDirectory(
            prefix="clawsona-mpv-", dir="/tmp"
        )
        self._socket = Path(self._directory.name) / "player.sock"
        try:
            self._process = await asyncio.create_subprocess_exec(
                binary,
                "--no-config",
                "--load-scripts=no",
                "--ytdl=no",
                "--idle=yes",
                "--no-video",
                "--audio-display=no",
                "--no-terminal",
                "--input-media-keys=no",
                "--pause=yes",
                "--volume-max=100",
                f"--input-ipc-server={self._socket}",
                *self._extra_args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            async with asyncio.timeout(10):
                while not self._socket.exists():
                    if not self.running:
                        raise PlaybackError("Не удалось запустить музыкальный плеер")
                    await asyncio.sleep(0.02)
        except BaseException:
            await self.close()
            raise

    @asynccontextmanager
    async def _connection(self):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self._socket), 2
            )
        except (OSError, TimeoutError) as exc:
            raise PlaybackError("Музыкальный плеер недоступен") from exc
        try:
            yield reader, writer
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def _request(self, command, *, wait_loaded=False):
        try:
            return await self._exchange(command, wait_loaded=wait_loaded)
        except TimeoutError as exc:
            raise PlaybackError(
                "Не удалось дождаться ответа музыкального плеера"
            ) from exc
        except (OSError, ValueError) as exc:
            raise PlaybackError(
                "Не удалось прочитать ответ музыкального плеера"
            ) from exc

    async def _exchange(self, command, *, wait_loaded=False):
        async with asyncio.timeout(25 if wait_loaded else 3):
            async with self._connection() as (reader, writer):
                writer.write(
                    (json.dumps({"command": command, "request_id": 1}) + "\n").encode()
                )
                await writer.drain()
                accepted = loaded = False
                result = None
                while raw := await reader.readline():
                    message = json.loads(raw)
                    if message.get("request_id") == 1:
                        if message.get("error") != "success":
                            raise PlaybackError(
                                "Плеер не смог выполнить музыкальную команду"
                            )
                        accepted, result = True, message.get("data")
                    if message.get("event") == "file-loaded":
                        loaded = True
                    if (
                        wait_loaded
                        and message.get("event") == "end-file"
                        and message.get("reason") == "error"
                    ):
                        raise PlaybackError("Плеер не смог открыть музыкальный поток")
                    if accepted and (loaded or not wait_loaded):
                        return result
                raise PlaybackError("Соединение с музыкальным плеером закрыто")

    async def load(self, url, *, volume, paused):
        await self._start()
        try:
            await self._request(["set_property", "pause", True])
            await self.set_volume(volume)
            await self._request(["loadfile", url, "replace"], wait_loaded=True)
            await self.set_paused(paused)
        except BaseException:
            # A timed-out load must not start playing later, after an error reply.
            await self.close()
            raise

    async def active(self):
        return self.running and not await self._request(["get_property", "idle-active"])

    async def set_paused(self, value):
        if self.running:
            await self._request(["set_property", "pause", bool(value)])

    async def set_volume(self, value):
        if self.running:
            await self._request(["set_property", "volume", value])

    async def stop(self):
        if self.running:
            await self._request(["stop"])

    async def close(self):
        process, self._process = self._process, None
        try:
            if process is not None and process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        finally:
            if self._directory is not None:
                self._directory.cleanup()
                self._directory = self._socket = None
