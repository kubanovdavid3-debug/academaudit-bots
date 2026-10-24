"""
Точка запуска бота публикаций AcademAudit Publisher (@AcademAuditPublishBot)
с автоматическим HTTP-healthcheck для облачных платформ.
Все клиентские заявки и призывы к действию (CTA) ведут напрямую в Telegram
администратора (@AcademAudit_Support) и на лендинг сервиса.
"""

import os
import sys
import asyncio
import logging
from aiohttp import web

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
            text="OK: AcademAudit Publisher Bot is running 24/7",
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
    logger.info("Запуск бота публикаций AcademAudit Publisher (@AcademAuditPublishBot)...")
    tasks = [
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
        logger.info("Бот публикаций остановлен.")
