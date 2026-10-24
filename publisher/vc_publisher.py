"""
Модуль публикации лонгридов на VC.ru (платформа Osnova) сервиса AcademAudit.
Преобразует Markdown в структуру блоков Editor.js, сохраняет JSON-копии в content/published/
и отправляет статьи через современное API VC.ru (v2.1/editor и v3.4/auth/refresh).
"""

import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import aiohttp
from dotenv import load_dotenv, set_key

from publisher.base import BasePublisher, ArticlePayload, PublishResult

logger = logging.getLogger("VCPublisher")


def slugify(text: str) -> str:
    """Генерирует латинский slug из русского текста."""
    translit_dict = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }
    text = text.lower().strip()
    result = []
    for char in text:
        if char in translit_dict:
            result.append(translit_dict[char])
        elif char.isalnum():
            result.append(char)
        elif char in [' ', '-', '_']:
            result.append('-')
    slug = ''.join(result)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug[:50] if slug else "article"


class VCPublisher(BasePublisher):
    """Паблишер для публикации статей на VC.ru (Osnova API)."""

    VC_API_BASE = "https://api.vc.ru/v2.1"
    VC_AUTH_URL = "https://api.vc.ru/v3.4/auth/refresh"
    STORAGE_DIR = Path("d:/temka/content/published")
    ENV_PATH = Path("d:/temka/.env")

    def __init__(
        self,
        refresh_token: Optional[str] = None,
        api_token: Optional[str] = None,
        subsite_id: Optional[str | int] = None,
        is_draft: bool = False,
    ):
        """
        Инициализация паблишера VC.ru.
        
        :param refresh_token: Токен обновления сессии (auth-refresh-token)
        :param api_token: Прямой JWT access_token (если есть)
        :param subsite_id: ID профиля/подсайта (по умолчанию 6158482)
        :param is_draft: Если True, сохранять только в черновики
        """
        load_dotenv(dotenv_path=self.ENV_PATH, override=True)

        self.refresh_token = (refresh_token or os.getenv("VC_REFRESH_TOKEN", "")).strip()
        self.api_token = (api_token or os.getenv("VC_API_TOKEN", "")).strip()
        self.is_draft = is_draft

        raw_subsite_id = subsite_id or os.getenv("VC_SUBSITE_ID", "6158482")
        try:
            self.subsite_id = int(str(raw_subsite_id).strip()) if raw_subsite_id else 6158482
        except ValueError:
            self.subsite_id = 6158482

        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    async def _obtain_access_token(self, session: aiohttp.ClientSession) -> Tuple[Optional[str], Optional[str]]:
        """
        Обменивает refresh_token на свежий JWT access_token и ротирует refresh_token.
        """
        if not self.refresh_token:
            return self.api_token or None, None

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://vc.ru",
            "Referer": "https://vc.ru/",
        }

        form_data = aiohttp.FormData()
        form_data.add_field("token", self.refresh_token)

        try:
            async with session.post(self.VC_AUTH_URL, data=form_data, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    res_data = data.get("data", {})
                    access_token = res_data.get("accessToken")
                    new_rt = res_data.get("refreshToken")

                    if new_rt:
                        self.refresh_token = new_rt
                        try:
                            set_key(str(self.ENV_PATH), "VC_REFRESH_TOKEN", new_rt)
                        except Exception as se:
                            logger.warning(f"Не удалось обновить VC_REFRESH_TOKEN в .env: {se}")

                    if access_token:
                        self.api_token = access_token
                        return access_token, None
                else:
                    err_txt = await resp.text()
                    return None, f"Ошибка обновления токена VC.ru (HTTP {resp.status}): {err_txt[:150]}"
        except Exception as e:
            return None, f"Исключение при обновлении токена VC.ru: {str(e)}"

        return self.api_token or None, None

    def parse_markdown_to_blocks(self, text: str, cta_link: str) -> List[Dict[str, Any]]:
        """
        Парсер Markdown в блочную структуру VC Editor.js:
        - H2 (##) -> Header style h2
        - H3 (###) -> Header style h3
        - H4 (####) -> Header style h3
        - Списки (— , - , * , 1. ) -> List (ordered / unordered)
        - Цитаты (> ) -> Quote
        - Обычный текст -> Paragraph
        """
        blocks: List[Dict[str, Any]] = []
        raw_paragraphs = text.split("\n\n")

        for section in raw_paragraphs:
            section = section.strip()
            if not section:
                continue

            lines = section.split("\n")
            first_line = lines[0].strip()

            # 1. Заголовки (H2, H3, H4)
            if first_line.startswith("#### "):
                blocks.append({
                    "type": "header",
                    "cover": False,
                    "hidden": False,
                    "anchor": "",
                    "data": {"text": first_line[5:].strip(), "style": "h3"}
                })
                continue
            elif first_line.startswith("### "):
                blocks.append({
                    "type": "header",
                    "cover": False,
                    "hidden": False,
                    "anchor": "",
                    "data": {"text": first_line[4:].strip(), "style": "h3"}
                })
                continue
            elif first_line.startswith("## "):
                blocks.append({
                    "type": "header",
                    "cover": False,
                    "hidden": False,
                    "anchor": "",
                    "data": {"text": first_line[3:].strip(), "style": "h2"}
                })
                continue
            elif first_line.startswith("# "):
                blocks.append({
                    "type": "header",
                    "cover": False,
                    "hidden": False,
                    "anchor": "",
                    "data": {"text": first_line[2:].strip(), "style": "h2"}
                })
                continue

            # 2. Цитаты (> ...)
            if first_line.startswith(">"):
                quote_text = " ".join([l.lstrip(">").strip() for l in lines])
                blocks.append({
                    "type": "quote",
                    "cover": False,
                    "hidden": False,
                    "anchor": "",
                    "data": {"text": quote_text, "subline1": "Экспертиза AcademAudit"}
                })
                continue

            # 3. Маркированные списки (-, *, —, •)
            is_unordered = any(first_line.startswith(prefix) for prefix in ["- ", "* ", "— ", "• "])
            if is_unordered:
                items = []
                for line in lines:
                    line = line.strip()
                    for prefix in ["- ", "* ", "— ", "• "]:
                        if line.startswith(prefix):
                            items.append(line[len(prefix):].strip())
                            break
                    else:
                        if items:
                            items[-1] += f" {line}"
                        else:
                            items.append(line)
                blocks.append({
                    "type": "list",
                    "cover": False,
                    "hidden": False,
                    "anchor": "",
                    "data": {"type": "unordered", "items": items}
                })
                continue

            # 4. Нумерованные списки (1. , 2. )
            is_ordered = bool(re.match(r"^\d+\.\s+", first_line))
            if is_ordered:
                items = []
                for line in lines:
                    line = line.strip()
                    matched = re.match(r"^\d+\.\s+(.*)", line)
                    if matched:
                        items.append(matched.group(1).strip())
                    else:
                        if items:
                            items[-1] += f" {line}"
                        else:
                            items.append(line)
                blocks.append({
                    "type": "list",
                    "cover": False,
                    "hidden": False,
                    "anchor": "",
                    "data": {"type": "ordered", "items": items}
                })
                continue

            # 5. Обычный абзац (Paragraph)
            clean_p = " ".join([l.strip() for l in lines])
            clean_p = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", clean_p)
            clean_p = re.sub(r"\*(.*?)\*", r"<i>\1</i>", clean_p)

            blocks.append({
                "type": "paragraph",
                "cover": False,
                "hidden": False,
                "anchor": "",
                "data": {"text": clean_p}
            })

        # Финальный конверсионный CTA-блок со ссылкой на бота
        cta_url = cta_link or "https://t.me/AcademAuditBot?start=vc_longread"
        blocks.append({
            "type": "paragraph",
            "cover": False,
            "hidden": False,
            "anchor": "",
            "data": {
                "text": (
                    "<br>━━━━━━━━━━━━━━━━━━━━<br>"
                    "<b>Сервис «AcademAudit»:</b> Независимый аудит тем и проверка студенческих работ "
                    "по стандартам ГОСТ 7.32 и Антиплагиат.ВУЗ 2026 без предоплаты.<br>"
                    f"👉 <b><a href='{cta_url}'>Рассчитать стоимость и проверить курсовую в боте</a></b>"
                )
            }
        })

        return blocks

    def save_payload_backup(self, article: ArticlePayload, blocks: List[Dict[str, Any]], final_payload: Dict[str, Any]) -> Path:
        """Сохраняет копию полезного payload в content/published/{date}_{slug}.json."""
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug_str = slugify(article.title)
        filename = f"{date_str}_{slug_str}.json"
        filepath = self.STORAGE_DIR / filename

        archive_data = {
            "meta": {
                "created_at": datetime.now().isoformat(),
                "title": article.title,
                "slug": slug_str,
                "tags": article.tags,
                "cta_link": article.cta_link,
                "is_draft": self.is_draft,
                "subsite_id": self.subsite_id,
            },
            "article_payload": article.model_dump(),
            "editor_js_blocks": blocks,
            "api_request_payload": final_payload,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Архивная копия полезного payload сохранена: {filepath}")
        return filepath

    async def publish(self, article: ArticlePayload) -> PublishResult:
        """
        Публикует статью на VC.ru или сохраняет черновик.
        
        :param article: Объект ArticlePayload
        :return: PublishResult
        """
        # 1. Парсинг текста в блоки Editor.js
        blocks = self.parse_markdown_to_blocks(article.text, article.cta_link)

        # 2. Формирование структуры записи для VC.ru
        entry_data = {
            "id": 0,
            "user_id": self.subsite_id or 0,
            "subsite_id": self.subsite_id or 0,
            "type": 1,
            "title": article.title,
            "entry": {
                "blocks": blocks
            },
            "external_access_link": "",
            "path": "",
            "is_editorial": False,
            "is_advertisement": False,
            "is_enabled_comments": True,
            "is_enabled_likes": True,
            "withheld": False,
            "is_enabled_ad": True,
            "is_holdonflash": False,
            "forced_to_mainpage": 0,
            "is_holdonmain": False,
            "is_published": False,
            "is_adult": False,
            "repostId": None,
            "repostData": None
        }

        # 3. Сохранение бэкапа payload в content/published/
        backup_path = self.save_payload_backup(article, blocks, entry_data)

        async with aiohttp.ClientSession() as session:
            # 4. Получение / обновление токена
            access_token, token_err = await self._obtain_access_token(session)
            if not access_token:
                err_msg = (
                    f"Авторизация для VC.ru не удалась ({token_err or 'нет токена'}). "
                    f"Полезный payload сохранен в архив: {backup_path}"
                )
                logger.warning(err_msg)
                return PublishResult(
                    platform="vc",
                    success=False,
                    error_message=err_msg,
                )

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Origin": "https://vc.ru",
                "Referer": "https://vc.ru/",
                "Pwa": "1",
                "JWTAuthorization": f"Bearer {access_token}",
            }

            try:
                # 5. Сохранение записи в редактор через /v2.1/editor (FormData)
                fd = aiohttp.FormData()
                fd.add_field("entry", json.dumps(entry_data, ensure_ascii=False))

                async with session.post(f"{self.VC_API_BASE}/editor", data=fd, headers=headers) as resp:
                    resp_text = await resp.text()

                    if resp.status not in [200, 201]:
                        raise RuntimeError(f"HTTP {resp.status} от VC /editor: {resp_text[:200]}")

                    resp_data = json.loads(resp_text)
                    entry_obj = resp_data.get("result", {}).get("entry", {}) or resp_data.get("entry", {})
                    entry_id = entry_obj.get("id") or resp_data.get("id")
                    entry_url = entry_obj.get("url") or f"https://vc.ru/id{self.subsite_id}/{entry_id}"

                    if not entry_id:
                        raise RuntimeError(f"Не удалось получить id созданной записи: {resp_text[:200]}")

                    # 6. Если требуется немедленная публикация (не черновик)
                    if not self.is_draft:
                        publish_url = f"{self.VC_API_BASE}/editor/{entry_id}/publish"
                        pub_fd = aiohttp.FormData()
                        async with session.post(publish_url, data=pub_fd, headers=headers) as pub_resp:
                            if pub_resp.status in [200, 201]:
                                logger.info(f"Статья успешно опубликована на VC.ru: {entry_url}")
                                return PublishResult(
                                    platform="vc",
                                    success=True,
                                    post_url=entry_url,
                                )
                            else:
                                pub_err = await pub_resp.text()
                                logger.info(f"Черновик сохранен ({entry_id}), автопубликация вернула: {pub_err[:120]}")
                                return PublishResult(
                                    platform="vc",
                                    success=True,
                                    post_url=entry_url,
                                    error_message="Статья сохранена в черновиках автора профиля VC.ru (требуется клик 'Опубликовать' в редакторе по лимитам аккаунта)." if "PRO_LIMIT" in pub_err else None,
                                )
                    else:
                        logger.info(f"Черновик статьи сохранен на VC.ru: {entry_url}")
                        return PublishResult(
                            platform="vc",
                            success=True,
                            post_url=entry_url,
                        )

            except Exception as e:
                error_msg = f"Ошибка отправки на VC.ru: {str(e)}"
                logger.error(error_msg)
                return PublishResult(
                    platform="vc",
                    success=False,
                    error_message=error_msg,
                )
