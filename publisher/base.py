"""
Модуль базовых моделей и абстрактных классов для системы автопостинга AcademAudit.
"""

from abc import ABC, abstractmethod
from typing import Optional, List
from pydantic import BaseModel, Field


class ArticlePayload(BaseModel):
    """Модель входящей статьи для публикации."""
    title: str = Field(..., description="Заголовок статьи")
    text: str = Field(..., description="Основной текст статьи")
    excerpt: str = Field(default="", description="Краткое описание / лид статьи")
    tags: List[str] = Field(default_factory=list, description="Список тегов (без решеток или с ними)")
    cover_image_path: Optional[str] = Field(default=None, description="Локальный путь к изображению обложки")
    cta_link: str = Field(default="https://t.me/AcademAuditBot", description="Ссылка для призыва к действию (CTA)")
    source_platform: str = Field(default="custom", description="Платформа-источник (VC, Habr, Blog, AI)")


class PublishResult(BaseModel):
    """Результат выполнения публикации статьи."""
    platform: str = Field(..., description="Название платформы (например: telegram, vk, vc)")
    success: bool = Field(..., description="Флаг успешности отправки")
    post_url: Optional[str] = Field(default=None, description="Прямая ссылка на опубликованный материал")
    error_message: Optional[str] = Field(default=None, description="Текст ошибки в случае сбоя")


class BasePublisher(ABC):
    """Абстрактный базовый класс для всех платформ публикации."""

    @abstractmethod
    async def publish(self, article: ArticlePayload) -> PublishResult:
        """
        Опубликовать статью на целевой платформе.
        
        :param article: Данные статьи (заголовок, текст, теги, обложка, ссылка)
        :return: PublishResult с результатом публикации
        """
        pass
