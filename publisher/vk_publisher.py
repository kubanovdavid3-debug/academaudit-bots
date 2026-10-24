"""
Модуль публикации статей на стену сообщества ВКонтакте сервиса AcademAudit.
Использует асинхронный клиент aiohttp и официальный VK API v5.199.
"""

import os
import re
import json
import logging
from typing import Optional, List
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

from publisher.base import BasePublisher, ArticlePayload, PublishResult

logger = logging.getLogger("VKPublisher")


class VKPublisher(BasePublisher):
    """Паблишер для публикации контента в сообщество ВКонтакте."""

    VK_API_VERSION = "5.199"
    VK_API_BASE = "https://api.vk.com/method"

    # Маппинг частых ошибок VK API для информативных сообщений
    ERROR_DESCRIPTIONS = {
        5: "Ошибка авторизации VK (Error 5): Недействительный или истекший VK_ACCESS_TOKEN. Получите новый токен с правами: wall, photos, offline, groups.",
        6: "Превышен лимит частоты запросов (Error 6): Too many requests per second. Сделайте паузу перед следующим запросом.",
        7: "Нет прав на выполнение действия (Error 7): Проверьте права токена.",
        10: "Внутренняя ошибка сервера ВКонтакте (Error 10). Попробуйте позже.",
        15: "Ошибка прав доступа (Error 15): Нет прав на публикацию на стене сообщества. Убедитесь, что токен принадлежит администратору группы и содержит scope 'wall'.",
        27: "Ошибка группы (Error 27): Неверно указан ID сообщества VK_OWNER_ID.",
        100: "Один из переданных параметров неверен (Error 100).",
        214: "Доступ к публикации на стене запрещен (Error 214): Стена группы закрыта или ограничена.",
    }

    def __init__(
        self,
        access_token: Optional[str] = None,
        owner_id: Optional[str | int] = None,
        bot_link: str = "https://t.me/AcademAudit_Support",
    ):
        """
        Инициализация паблишера ВКонтакте.
        
        :param access_token: Токен доступа VK (если None, берется из .env VK_ACCESS_TOKEN)
        :param owner_id: ID сообщества со знаком минус (например: -218800000)
        :param bot_link: Ссылка для связи (Telegram-менеджер или сайт)
        """
        load_dotenv()

        self.access_token = (access_token or os.getenv("VK_ACCESS_TOKEN", "")).strip()
        raw_owner_id = owner_id or os.getenv("VK_OWNER_ID", "")
        self.bot_link = bot_link or f"https://t.me/{os.getenv('MANAGER_USERNAME', 'AcademAudit_Support')}"

        # Преобразуем owner_id в числовой отрицательный ID сообщества
        try:
            self.owner_id = int(str(raw_owner_id).strip())
            # Сообщества в VK имеют отрицательный ID
            if self.owner_id > 0:
                self.owner_id = -self.owner_id
        except ValueError:
            self.owner_id = None

    def _strip_html_tags(self, text: str) -> str:
        """Очищает HTML-теги для читаемого отображения на стене VK."""
        # Заменяем <br> и </p> на переносы строк
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        # Удаляем остальные HTML теги (<b>, <i>, <code> и т.д.)
        clean_text = re.sub(r"<[^>]+>", "", text)
        return clean_text.strip()

    def _format_tags(self, tags: List[str]) -> str:
        """Форматирует теги в хештеги VK с добавлением обязательных брендовых тегов."""
        mandatory_tags = ["курсовая", "антиплагиат", "AcademAudit"]
        combined = list(mandatory_tags)

        for t in tags:
            clean = t.strip().lstrip("#").replace(" ", "_").replace("-", "_")
            if clean and clean.lower() not in [m.lower() for m in combined]:
                combined.append(clean)

        return " ".join([f"#{t}" for t in combined])

    async def _call_api(self, session: aiohttp.ClientSession, method: str, params: dict) -> dict:
        """Выполняет вызов метода VK API с проверкой ошибок."""
        url = f"{self.VK_API_BASE}/{method}"
        payload = {
            **params,
            "access_token": self.access_token,
            "v": self.VK_API_VERSION,
        }

        async with session.post(url, data=payload) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP ошибка VK API: {response.status}")

            data = await response.json()

            if "error" in data:
                err = data["error"]
                code = err.get("error_code", 0)
                msg = err.get("error_msg", "Неизвестная ошибка")

                custom_desc = self.ERROR_DESCRIPTIONS.get(code)
                if custom_desc:
                    raise RuntimeError(f"{custom_desc} (VK Msg: {msg})")
                raise RuntimeError(f"Ошибка VK API #{code}: {msg}")

            return data.get("response", {})

    async def _upload_wall_photo(
        self, session: aiohttp.ClientSession, image_path: str, group_id: int
    ) -> Optional[str]:
        """
        Загружает фото на стену сообщества в 3 этапа по спецификации VK API:
        1. photos.getWallUploadServer
        2. POST multipart/form-data на полученный upload_url
        3. photos.saveWallPhoto
        """
        path = Path(image_path)
        if not path.exists() or not path.is_file():
            logger.warning(f"Файл обложки не найден: {image_path}")
            return None

        # Шаг 1: Получаем upload_url
        server_data = await self._call_api(
            session, "photos.getWallUploadServer", {"group_id": group_id}
        )
        upload_url = server_data.get("upload_url")
        if not upload_url:
            raise RuntimeError("Не удалось получить upload_url от VK API.")

        # Шаг 2: Загружаем файл на сервер VK
        data = aiohttp.FormData()
        with open(path, "rb") as f:
            data.add_field(
                "photo",
                f.read(),
                filename=path.name,
                content_type="image/jpeg" if path.suffix.lower() in [".jpg", ".jpeg"] else "image/png",
            )

        async with session.post(upload_url, data=data) as upload_resp:
            if upload_resp.status != 200:
                raise RuntimeError(f"Сбой загрузки файла на сервер VK: HTTP {upload_resp.status}")

            upload_result = await upload_resp.json()

        # Шаг 3: Сохраняем фото в альбом стены
        save_params = {
            "group_id": group_id,
            "photo": upload_result.get("photo"),
            "server": upload_result.get("server"),
            "hash": upload_result.get("hash"),
        }
        saved_photos = await self._call_api(session, "photos.saveWallPhoto", save_params)

        if saved_photos and isinstance(saved_photos, list) and len(saved_photos) > 0:
            photo_obj = saved_photos[0]
            attachment_id = f"photo{photo_obj['owner_id']}_{photo_obj['id']}"
            logger.info(f"Обложка успешно загружена в VK: {attachment_id}")
            return attachment_id

        return None

    async def publish(self, article: ArticlePayload) -> PublishResult:
        """
        Публикует статью на стену сообщества ВКонтакте.
        
        :param article: Объект ArticlePayload
        :return: PublishResult
        """
        if not self.access_token:
            return PublishResult(
                platform="vk",
                success=False,
                error_message="VK_ACCESS_TOKEN не задан в конфигурации (.env или параметрах).",
            )

        if not self.owner_id:
            return PublishResult(
                platform="vk",
                success=False,
                error_message="VK_OWNER_ID не задан или некорректен (должен быть числовым ID группы, например: -218800000).",
            )

        # Положительный ID группы для методов photos.*
        group_id = abs(self.owner_id)

        try:
            async with aiohttp.ClientSession() as session:
                # 1. Загрузка обложки, если указана
                attachments: List[str] = []
                if article.cover_image_path:
                    try:
                        photo_attachment = await self._upload_wall_photo(
                            session, article.cover_image_path, group_id
                        )
                        if photo_attachment:
                            attachments.append(photo_attachment)
                    except Exception as img_err:
                        logger.warning(f"Не удалось загрузить обложку в VK ({img_err}), публикуем только текст.")

                # 2. Форматирование текста статьи для стены VK
                clean_title = self._strip_html_tags(article.title)
                clean_text = self._strip_html_tags(article.text)
                tags_str = self._format_tags(article.tags)

                target_cta_link = article.cta_link or self.bot_link

                # Сборка финального сообщения
                message_parts = [
                    f"{clean_title}\n",
                    clean_text,
                    "\n━━━━━━━━━━━━━━━━━━━━",
                    "🔍 Бесплатный аудит темы и расчет стоимости курсовой по ГОСТ 2026 без предоплаты:",
                    f"👉 Написать эксперту: {target_cta_link}",
                    f"\n{tags_str}",
                ]
                full_message = "\n".join(message_parts)

                # 3. Публикация записи на стене (wall.post)
                wall_params = {
                    "owner_id": self.owner_id,
                    "from_group": 1,
                    "message": full_message,
                }
                if attachments:
                    wall_params["attachments"] = ",".join(attachments)

                post_data = await self._call_api(session, "wall.post", wall_params)
                post_id = post_data.get("post_id")

                if not post_id:
                    raise RuntimeError("VK API не вернул post_id опубликованной записи.")

                post_url = f"https://vk.com/wall{self.owner_id}_{post_id}"
                logger.info(f"Статья успешно опубликована на стене VK: {post_url}")

                return PublishResult(
                    platform="vk",
                    success=True,
                    post_url=post_url,
                )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Ошибка публикации в VK: {error_msg}")
            return PublishResult(
                platform="vk",
                success=False,
                error_message=error_msg,
            )
