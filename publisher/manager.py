"""
Менеджер мультиплатформенной публикации статей AcademAudit (PublisherManager).
Оркестрирует отправку контента в Telegram, ВКонтакте и VC.ru параллельно.
"""

import os
import asyncio
import logging
from typing import List, Dict, Optional, Any

from dotenv import load_dotenv

from publisher.base import ArticlePayload, PublishResult, BasePublisher
from publisher.tg_channel import TelegramChannelPublisher
from publisher.vk_publisher import VKPublisher
from publisher.vc_publisher import VCPublisher

logger = logging.getLogger("PublisherManager")


class PublisherManager:
    """Оркестратор публикации постов и лонгридов в различные социальные каналы."""

    TARGET_MAP = {
        "tg": "telegram",
        "telegram": "telegram",
        "tlg": "telegram",
        "vk": "vk",
        "vkontakte": "vk",
        "vc": "vc",
        "vcru": "vc",
        "vc_ru": "vc",
    }

    def __init__(self):
        load_dotenv()
        self._publishers: Dict[str, BasePublisher] = {}
        self._init_publishers()

    def _init_publishers(self):
        """Ленивая инициализация доступных паблишеров."""
        # 1. Telegram
        bot_token = os.getenv("PUBLISHER_BOT_TOKEN")
        channel_id = os.getenv("TG_CHANNEL_ID")
        bot_username = os.getenv("CLIENT_BOT_USERNAME", "AcademAuditBot")

        if bot_token and channel_id:
            self._publishers["telegram"] = TelegramChannelPublisher(
                bot_token=bot_token,
                channel_id=channel_id,
                bot_username=bot_username,
            )
        else:
            logger.warning("Telegram паблишер не инициализирован (отсутствует PUBLISHER_BOT_TOKEN или TG_CHANNEL_ID).")

        # 2. VK
        vk_token = os.getenv("VK_ACCESS_TOKEN")
        vk_owner_id = os.getenv("VK_OWNER_ID")
        if vk_token and vk_owner_id:
            self._publishers["vk"] = VKPublisher()
        else:
            logger.warning("VK паблишер не инициализирован (отсутствует VK_ACCESS_TOKEN или VK_OWNER_ID).")

        # 3. VC.ru
        self._publishers["vc"] = VCPublisher()

    def normalize_targets(self, targets: List[str]) -> List[str]:
        """Приводит список таргетов к каноническим названиям (telegram, vk, vc)."""
        normalized = []
        for t in targets:
            cleaned = t.strip().lower()
            canonical = self.TARGET_MAP.get(cleaned)
            if canonical and canonical not in normalized:
                normalized.append(canonical)
            elif not canonical:
                logger.warning(f"Неизвестная платформа '{t}', пропускаем.")
        return normalized

    async def publish_all(self, article: ArticlePayload, targets: List[str]) -> Dict[str, PublishResult]:
        """
        Асинхронно публикует статью на выбранных платформах.
        
        :param article: Объект статьи ArticlePayload
        :param targets: Список платформ, например ['tg', 'vk', 'vc']
        :return: Словарь вида { 'telegram': PublishResult, 'vk': PublishResult, 'vc': PublishResult }
        """
        norm_targets = self.normalize_targets(targets)
        results: Dict[str, PublishResult] = {}

        if not norm_targets:
            logger.error("Не указано ни одной поддерживаемой целевой платформы.")
            return results

        tasks = []
        task_platform_names = []

        for plat in norm_targets:
            publisher = self._publishers.get(plat)
            if not publisher:
                results[plat] = PublishResult(
                    platform=plat,
                    success=False,
                    error_message=f"Паблишер для '{plat}' не настроен (проверьте .env)",
                )
                continue

            tasks.append(publisher.publish(article))
            task_platform_names.append(plat)

        if tasks:
            # Параллельный запуск всех паблишеров
            executed_results = await asyncio.gather(*tasks, return_exceptions=True)

            for plat_name, res in zip(task_platform_names, executed_results):
                if isinstance(res, Exception):
                    results[plat_name] = PublishResult(
                        platform=plat_name,
                        success=False,
                        error_message=f"Исключение при публикации: {str(res)}",
                    )
                elif isinstance(res, PublishResult):
                    results[plat_name] = res
                else:
                    results[plat_name] = PublishResult(
                        platform=plat_name,
                        success=False,
                        error_message=f"Неизвестный ответ: {res}",
                    )

        return results
