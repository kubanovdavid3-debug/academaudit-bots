"""
Точка одновременного запуска обоих ботов AcademAudit:
1. @AcademAuditBot (клиентский лид-бот для студентов)
2. @AcademAuditPublishBot (бот редакции и автопостинга для администратора)
"""

import asyncio
import logging
import sys

from main import main as run_client_bot
from publisher_bot import main as run_publisher_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("AcademAuditRunner")


async def run_ecosystem():
    logger.info("Запуск экосистемы AcademAudit (Лид-бот + Бот редакции)...")
    await asyncio.gather(
        run_client_bot(),
        run_publisher_bot(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(run_ecosystem())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Все боты сервиса остановлены.")
