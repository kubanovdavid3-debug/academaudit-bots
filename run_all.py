"""
Точка одновременного запуска обоих ботов AcademAudit:
1. @AcademAuditBot (клиентский лид-бот для студентов)
2. @AcademAuditPublishBot (бот редакции и автопостинга для администратора)
Включает автоматический HTTP-healthcheck для облачных платформ (Koyeb, Render).
"""

import os
import sys
import asyncio
import logging
from aiohttp import web

from main import main as run_client_bot
from publisher_bot import main as run_publisher_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("AcademAuditRunner")


async def start_healthcheck_server(port: int = 8000):
    """Легковесный HTTP-сервер для прохождения health check в облачных сервисах."""
    async def handle_health(request):
        return web.Response(
            text="OK: AcademAudit Bot Ecosystem is running 24/7",
            content_type="text/plain",
        )

    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Healthcheck HTTP-сервер активен на 0.0.0.0:{port}")


async def run_ecosystem():
    logger.info("Запуск экосистемы AcademAudit (Лид-бот + Бот редакции)...")
    tasks = [
        run_client_bot(),
        run_publisher_bot(),
    ]

    # Если хостинг передает переменную окружения PORT (Koyeb, Render и др.)
    port_env = os.getenv("PORT")
    if port_env:
        try:
            port = int(port_env)
            tasks.append(start_healthcheck_server(port))
        except ValueError:
            logger.warning(f"Некорректный порт в переменной PORT: {port_env}")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(run_ecosystem())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Все боты сервиса остановлены.")
