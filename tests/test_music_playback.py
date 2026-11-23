import asyncio
import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from clawsona.music_playback import MpvPlayback, PlaybackError


@asynccontextmanager
async def ipc_player(handler):
    # pytest's generated paths can exceed macOS's Unix socket path limit.
    with tempfile.TemporaryDirectory(prefix="clawsona-test-", dir="/tmp") as directory:
        path = Path(directory) / "ipc"

        async def accept(reader, writer):
            try:
                message = json.loads(await reader.readline())
                await handler(message, writer)
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_unix_server(accept, path)
        playback = MpvPlayback()
        playback._socket = path
        playback._process = MagicMock(returncode=None, wait=AsyncMock(return_value=0))
        try:
            async with server:
                yield playback
        finally:
            await playback.close()


@pytest.mark.asyncio
async def test_load_waits_for_file_loaded_before_unpausing():
    commands = []
    load_seen, allow_load = asyncio.Event(), asyncio.Event()

    async def handler(message, writer):
        commands.append(message["command"])
        writer.write(b'{"request_id":1,"error":"success"}\n')
        await writer.drain()
        if message["command"][0] == "loadfile":
            load_seen.set()
            await allow_load.wait()
            writer.write(b'{"event":"file-loaded"}\n')
            await writer.drain()

    async with ipc_player(handler) as playback:
        task = asyncio.create_task(
            playback.load("https://music.yandex.net/test", volume=65, paused=False)
        )
        await asyncio.wait_for(load_seen.wait(), 2)
        assert not task.done()
        assert ["set_property", "pause", False] not in commands
        allow_load.set()
        await asyncio.wait_for(task, 2)
        assert commands[-1] == ["set_property", "pause", False]
        assert ["set_property", "volume", 65] in commands


@pytest.mark.asyncio
async def test_failed_stream_is_not_reported_as_playing_and_private_url_is_hidden():
    async def handler(message, writer):
        writer.write(b'{"request_id":1,"error":"success"}\n')
        if message["command"][0] == "loadfile":
            writer.write(
                b'{"event":"end-file","reason":"error","file_error":"private-signed-url"}\n'
            )
        await writer.drain()

    async with ipc_player(handler) as playback:
        process = playback._process
        with pytest.raises(PlaybackError) as error:
            await playback.load(
                "https://music.yandex.net/private-signed-url", volume=50, paused=False
            )
        assert "private-signed-url" not in str(error.value)
        process.terminate.assert_called_once()
        assert not playback.running


@pytest.mark.asyncio
async def test_volume_command_ack_is_required():
    async def handler(message, writer):
        writer.write(b'{"request_id":1,"error":"property unavailable"}\n')
        await writer.drain()

    async with ipc_player(handler) as playback:
        with pytest.raises(PlaybackError):
            await playback.set_volume(75)


@pytest.mark.asyncio
async def test_missing_mpv_reports_installation_instructions(mocker):
    mocker.patch("clawsona.music_playback.shutil.which", return_value=None)
    with pytest.raises(PlaybackError, match="install mpv"):
        await MpvPlayback().load(
            "https://music.yandex.net/test", volume=50, paused=False
        )
