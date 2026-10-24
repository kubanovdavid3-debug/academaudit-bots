"""
Пакет автопостинга статей сервиса AcademAudit.
Поддерживает Telegram-каналы, сообщества ВКонтакте и лонгриды VC.ru.
"""

from publisher.base import ArticlePayload, PublishResult, BasePublisher
from publisher.tg_channel import TelegramChannelPublisher
from publisher.vk_publisher import VKPublisher
from publisher.vc_publisher import VCPublisher
from publisher.manager import PublisherManager

__all__ = [
    "ArticlePayload",
    "PublishResult",
    "BasePublisher",
    "TelegramChannelPublisher",
    "VKPublisher",
    "VCPublisher",
    "PublisherManager",
]
