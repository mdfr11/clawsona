import asyncio
import secrets
import uuid
from contextlib import asynccontextmanager

from aiohttp import web

from clawsona.agent_tools import weather, web_search
from clawsona.music import YandexMusicPlayer
from clawsona.timing import stage_timer, timing_context


def create_tool_app(config, music=None):
    player = (
        music
        if music is not None
        else (YandexMusicPlayer(config) if config.music_enabled else None)
    )

    @web.middleware
    async def authorize(request, handler):
        expected = f"Bearer {config.clawsona_tools_token}".encode()
        if not config.clawsona_tools_token or not secrets.compare_digest(
            request.headers.get("Authorization", "").encode(), expected
        ):
            raise web.HTTPUnauthorized()
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception as exc:
            # SDK exceptions can include account URLs. Keep credentials out of responses.
            message = str(exc)
            for secret in (
                config.yandex_music_token,
                getattr(player, "_token", ""),
                config.deepseek_api_key,
                config.clawsona_tools_token,
            ):
                if secret:
                    message = message.replace(secret, "[redacted]")
            return web.json_response({"error": message[:300]}, status=400)

    app = web.Application(middlewares=[authorize], client_max_size=8192)

    async def execute(request):
        operation = request.match_info["operation"]
        with (
            timing_context(tool_call=uuid.uuid4().hex[:8]),
            stage_timer("tool", operation=operation),
        ):
            return await execute_tool(request, operation)

    async def execute_tool(request, operation):
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("Ожидается объект параметров")
        if operation == "weather":
            result = await weather(data.get("city", ""), data.get("day_offset", 0))
        elif operation == "search":
            result = await web_search(data.get("query", ""), config.deepseek_api_key)
        elif operation == "music":
            if not config.music_enabled or player is None:
                raise ValueError("Музыка отключена в этой установке")
            options = {key: data[key] for key in ("volume", "step") if key in data}
            try:
                async with asyncio.timeout(40):
                    result = await player.command(
                        data.get("action", "status"), data.get("query", ""), **options
                    )
            except TimeoutError as exc:
                raise ValueError(
                    "Музыкальная команда не завершилась вовремя. Попробуйте ещё раз."
                ) from exc
        else:
            raise web.HTTPNotFound()
        return web.json_response(result)

    app.router.add_post("/{operation}", execute)

    async def cleanup(_app):
        if player is not None:
            await player.close()

    app.on_cleanup.append(cleanup)
    return app


@asynccontextmanager
async def serve_tools(config):
    if not config.clawsona_tools_token:
        raise ValueError(
            "Выполните clawsona openclaw-setup для настройки локальных инструментов"
        )
    player = YandexMusicPlayer(config) if config.music_enabled else None
    runner = web.AppRunner(create_tool_app(config, player), access_log=None)
    try:
        with stage_timer("startup_tools"):
            await runner.setup()
            await web.TCPSite(runner, "127.0.0.1", config.clawsona_tools_port).start()
        yield player
    finally:
        await runner.cleanup()
