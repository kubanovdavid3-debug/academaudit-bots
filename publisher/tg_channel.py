"""
Модуль публикации статей в Telegram-канал сервиса AcademAudit.
Реализует адаптивную разбивку длинных лонгридов (>4096 символов), 
публикацию обложек и инлайн-кнопки конверсии в бота.
"""

import os
import logging
from typing import Optional, List
from pathlib import Path

from dotenv import load_dotenv
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
)
from aiogram.exceptions import TelegramAPIError

from publisher.base import BasePublisher, ArticlePayload, PublishResult

logger = logging.getLogger("TelegramChannelPublisher")


class TelegramChannelPublisher(BasePublisher):
    """Паблишер для публикации контента в Telegram-канал."""

    MAX_MESSAGE_LENGTH = 4096
    MAX_CAPTION_LENGTH = 1024
    SAFE_CHUNK_SIZE = 3900

    def __init__(
        self,
        bot_token: Optional[str] = None,
        channel_id: Optional[str] = None,
        bot_username: str = "AcademAuditBot",
    ):
        """
        Инициализация паблишера.
        
        :param bot_token: Токен бота Telegram (если None, берется из .env BOT_TOKEN)
        :param channel_id: ID канала (@channel_name или -100...) (если None, берется из .env TG_CHANNEL_ID)
        :param bot_username: Юзернейм бота для генерации инлайн-ссылки
        """
        load_dotenv()

        # Если токен не передан явно, берем токен бота-издателя PUBLISHER_BOT_TOKEN (или fallback на BOT_TOKEN)
        self.bot_token = (bot_token or os.getenv("PUBLISHER_BOT_TOKEN") or os.getenv("BOT_TOKEN", "")).strip()
        self.channel_id = (channel_id or os.getenv("TG_CHANNEL_ID", "")).strip()
        self.bot_username = bot_username.lstrip("@")

        if not self.bot_token:
            raise ValueError("Токен для публикаций не указан (задайте PUBLISHER_BOT_TOKEN или BOT_TOKEN в .env).")

    def _format_tags(self, tags: List[str]) -> str:
        """Форматирует теги в хештеги Telegram."""
        if not tags:
            return ""
        formatted = []
        for tag in tags:
            clean = tag.strip().lstrip("#").replace(" ", "_").replace("-", "_")
            if clean:
                formatted.append(f"#{clean}")
        return " ".join(formatted)

    def _build_inline_keyboard(self, cta_link: Optional[str] = None) -> InlineKeyboardMarkup:
        """Создает инлайн-клавиатуру с кнопкой перехода в бота и опциональным сайтом."""
        # Deep link со специальным параметром start=audit, чтобы бот сразу начинал проверку
        bot_url = f"https://t.me/{self.bot_username}?start=audit"
        buttons = [
            [
                InlineKeyboardButton(
                    text="🔍 Проверить курсовую в боте",
                    url=bot_url,
                )
            ]
        ]

        # Если передана внешняя ссылка (например, на калькулятор/сайт), добавляем вторую кнопку
        if cta_link and cta_link.strip() and not cta_link.startswith(bot_url):
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="🌐 Рассчитать на сайте",
                        url=cta_link.strip(),
                    )
                ]
            )

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    def _split_text(self, text: str, max_chunk_size: int = 3900) -> List[str]:
        """
        Разбивает текст на части с сохранением абзацев и границ предложений.
        """
        if len(text) <= max_chunk_size:
            return [text]

        chunks: List[str] = []
        paragraphs = text.split("\n\n")
        current_chunk = ""

        for p in paragraphs:
            p = p.strip()
            if not p:
                continue

            if len(current_chunk) + len(p) + 2 <= max_chunk_size:
                current_chunk = f"{current_chunk}\n\n{p}" if current_chunk else p
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""

                # Если сам по себе абзац больше max_chunk_size, режем по строкам или предложениям
                if len(p) > max_chunk_size:
                    lines = p.split("\n")
                    for line in lines:
                        if len(current_chunk) + len(line) + 1 <= max_chunk_size:
                            current_chunk = f"{current_chunk}\n{line}" if current_chunk else line
                        else:
                            if current_chunk:
                                chunks.append(current_chunk)
                            current_chunk = line
                else:
                    current_chunk = p

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _build_post_url(self, message_id: int) -> Optional[str]:
        """Генерирует публичную или внутреннюю ссылку на опубликованный пост."""
        if not self.channel_id:
            return None

        channel_str = str(self.channel_id).strip()
        if channel_str.startswith("@"):
            channel_name = channel_str.lstrip("@")
            return f"https://t.me/{channel_name}/{message_id}"
        elif channel_str.startswith("-100"):
            clean_id = channel_str[4:]
            return f"https://t.me/c/{clean_id}/{message_id}"
        return None

    async def publish(self, article: ArticlePayload) -> PublishResult:
        """
        Публикует статью в целевой канал Telegram.
        
        :param article: Объект ArticlePayload
        :return: PublishResult
        """
        if not self.channel_id:
            return PublishResult(
                platform="telegram",
                success=False,
                error_message="TG_CHANNEL_ID не задан в конфигурации (.env или аргументах).",
            )

        bot = Bot(
            token=self.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )

        try:
            tags_str = self._format_tags(article.tags)
            reply_markup = self._build_inline_keyboard(article.cta_link)

            # Проверяем наличие валидной обложки
            has_cover = False
            if article.cover_image_path:
                cover_path = Path(article.cover_image_path)
                if cover_path.exists() and cover_path.is_file():
                    has_cover = True
                else:
                    logger.warning(f"Файл обложки не найден по пути: {article.cover_image_path}")

            first_message: Optional[Message] = None

            # Сценарий 1: Публикация с обложкой
            if has_cover:
                photo_file = FSInputFile(str(article.cover_image_path))

                # Формируем полный текст статьи
                full_body = f"<b>{article.title}</b>\n\n{article.text}"
                if tags_str:
                    full_body = f"{full_body}\n\n{tags_str}"

                # Если статья целиком помещается в подпись к фото (1024 символа)
                if len(full_body) <= self.MAX_CAPTION_LENGTH:
                    first_message = await bot.send_photo(
                        chat_id=self.channel_id,
                        photo=photo_file,
                        caption=full_body,
                        reply_markup=reply_markup,
                    )
                else:
                    # Лонгрид с обложкой:
                    # 1. Отправляем фото с заголовком и лидом/кратким описанием
                    intro_caption = f"<b>{article.title}</b>"
                    if article.excerpt:
                        intro_caption += f"\n\n<i>{article.excerpt}</i>"
                    if tags_str:
                        intro_caption += f"\n\n{tags_str}"

                    # Гарантируем, что подпись не превышает 1024
                    if len(intro_caption) > self.MAX_CAPTION_LENGTH:
                        intro_caption = intro_caption[:1020] + "..."

                    first_message = await bot.send_photo(
                        chat_id=self.channel_id,
                        photo=photo_file,
                        caption=intro_caption,
                    )

                    # 2. Основной текст режем на читаемые блоки и отправляем следом
                    chunks = self._split_text(article.text, max_chunk_size=self.SAFE_CHUNK_SIZE)
                    for i, chunk in enumerate(chunks):
                        is_last = (i == len(chunks) - 1)
                        chunk_markup = reply_markup if is_last else None
                        await bot.send_message(
                            chat_id=self.channel_id,
                            text=chunk,
                            reply_markup=chunk_markup,
                            disable_web_page_preview=True,
                        )

            # Сценарий 2: Публикация без обложки (текстовый формат)
            else:
                full_text = f"<b>{article.title}</b>\n\n{article.text}"
                if tags_str:
                    full_text = f"{full_text}\n\n{tags_str}"

                # Если текст помещается в одно стандартное сообщение (4096 символов)
                if len(full_text) <= self.MAX_MESSAGE_LENGTH:
                    first_message = await bot.send_message(
                        chat_id=self.channel_id,
                        text=full_text,
                        reply_markup=reply_markup,
                        disable_web_page_preview=False,
                    )
                else:
                    # Длинный лонгрид без фото
                    header = f"<b>{article.title}</b>\n\n"
                    chunks = self._split_text(article.text, max_chunk_size=self.SAFE_CHUNK_SIZE)

                    for i, chunk in enumerate(chunks):
                        if i == 0:
                            content = f"{header}{chunk}"
                        else:
                            content = f"<i>(Продолжение)</i>\n\n{chunk}"

                        is_last = (i == len(chunks) - 1)
                        if is_last and tags_str:
                            content = f"{content}\n\n{tags_str}"

                        chunk_markup = reply_markup if is_last else None
                        msg = await bot.send_message(
                            chat_id=self.channel_id,
                            text=content,
                            reply_markup=chunk_markup,
                            disable_web_page_preview=True,
                        )
                        if i == 0:
                            first_message = msg

            post_url = self._build_post_url(first_message.message_id) if first_message else None
            logger.info(f"Статья успешно опубликована в Telegram ({self.channel_id}): {post_url}")

            return PublishResult(
                platform="telegram",
                success=True,
                post_url=post_url,
            )

        except TelegramAPIError as e:
            error_msg = f"Ошибка Telegram API: {e.message}"
            logger.error(error_msg)
            return PublishResult(
                platform="telegram",
                success=False,
                error_message=error_msg,
            )
        except Exception as e:
            error_msg = f"Непредвиденная ошибка при публикации: {str(e)}"
            logger.exception(error_msg)
            return PublishResult(
                platform="telegram",
                success=False,
                error_message=error_msg,
            )
        finally:
            await bot.session.close()
